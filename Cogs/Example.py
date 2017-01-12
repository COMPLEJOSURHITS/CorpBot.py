import asyncio
import discord
import random
import datetime
from   discord.ext import commands
from   Cogs import Settings
from   Cogs import DisplayName
from   Cogs import Nullify

if not discord.opus.is_loaded():
	# the 'opus' library here is opus.dll on windows
	# or libopus.so on linux in the current directory
	# you should replace this with the location the
	# opus library is located in and with the proper filename.
	# note that on windows this DLL is automatically provided for you
	discord.opus.load_opus('opus')

class Example:

	def __init__(self, bot):
		self.bot = bot

	@commands.command()
	async def add(self, left : int, right : int):
		"""Adds two numbers together."""
		await self.bot.say(left + right)

	@commands.command()
	async def roll(self, dice : str):
		"""Rolls a dice in NdN format."""
		try:
			rolls, limit = map(int, dice.split('d'))
		except Exception:
			await self.bot.say('Format has to be in NdN!')
			return

		result = ', '.join(str(random.randint(1, limit)) for r in range(rolls))
		await self.bot.say(result)

	@commands.command(description='For when you wanna settle the score some other way')
	async def choose(self, *choices : str):
		"""Chooses between multiple choices."""
		msg = random.choice(choices)
		msg = Nullify.clean(msg)
		await self.bot.say(msg)

	@commands.command(pass_context=True)
	async def joined(self, ctx, member : discord.Member = None):
		"""Says when a member joined."""

		if member == None:
			member = ctx.message.author

		await self.bot.say('{} joined {}'.format(DisplayName.name(member), member.joined_at.strftime("%Y-%m-%d %I:%M %p")))

class VoiceEntry:
	def __init__(self, message, player):
		self.requester = message.author
		self.channel = message.channel
		self.player = player

	def __str__(self):
		fmt = '*{0.title}* requested by {1.name}'
		duration = self.player.duration
		if duration:
			fmt = fmt + ' [length: {0[0]}m {0[1]}s]'.format(divmod(duration, 60))
		return fmt.format(self.player, self.requester)

class VoiceState:
	def __init__(self, bot):
		self.current = None
		self.voice = None
		self.bot = bot
		self.play_next_song = asyncio.Event()
		self.playlist = []
		self.votes = []
		self.audio_player = self.bot.loop.create_task(self.audio_player_task())
		self.start_time = datetime.datetime.now()
		self.total_playing_time = datetime.datetime.now() - datetime.datetime.now()
		self.is_paused = False

	def is_playing(self):
		if self.voice is None or self.current is None:
			return False

		player = self.current.player
		return not player.is_done()

	@property
	def player(self):
		return self.current.player

	def skip(self):
		self.votes = []
		if self.is_playing():
			self.player.stop()

	def toggle_next(self):
		self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

	async def audio_player_task(self):
		while True:
			self.play_next_song.clear()

			if len(self.playlist) <= 0:
				await asyncio.sleep(1)
				continue

			self.start_time = datetime.datetime.now()
			self.current = self.playlist[0]
			self.votes.append({ 'user' : self.current.requester, 'value' : 'keep' })
			await self.bot.send_message(self.current.channel, 'Now playing ' + str(self.current))

			self.current.player.start()
			await self.play_next_song.wait()
			del self.playlist[0]

class Music:
	"""Voice related commands.

	Works in multiple servers at once.
	"""
	def __init__(self, bot, settings):
		self.bot = bot
		self.voice_states = {}
		self.settings = settings

	def get_voice_state(self, server):
		state = self.voice_states.get(server.id)
		if state is None:
			state = VoiceState(self.bot)
			self.voice_states[server.id] = state

		return state

	async def create_voice_client(self, channel):
		voice = await self.bot.join_voice_channel(channel)
		state = self.get_voice_state(channel.server)
		state.voice = voice

	def __unload(self):
		for state in self.voice_states.values():
			try:
				state.audio_player.cancel()
				if state.voice:
					self.bot.loop.create_task(state.voice.disconnect())
			except:
				pass

	@commands.command(pass_context=True, no_pm=True)
	async def join(self, ctx, *, channel : discord.Channel):
		"""Joins a voice channel."""
		try:
			await self.create_voice_client(channel)
		except discord.ClientException:
			await self.bot.say('Already in a voice channel...')
		except discord.InvalidArgument:
			await self.bot.say('This is not a voice channel...')
		else:
			await self.bot.say('Ready to play audio in ' + channel.name)

	@commands.command(pass_context=True, no_pm=True)
	async def summon(self, ctx):
		"""Summons the bot to join your voice channel."""
		summoned_channel = ctx.message.author.voice_channel
		if summoned_channel is None:
			await self.bot.say('You are not in a voice channel.')
			return False

		state = self.get_voice_state(ctx.message.server)
		if state.voice is None:
			state.voice = await self.bot.join_voice_channel(summoned_channel)
		else:
			await state.voice.move_to(summoned_channel)

		return True

	@commands.command(pass_context=True, no_pm=True)
	async def play(self, ctx, *, song : str):
		"""Plays a song.

		If there is a song currently in the queue, then it is
		queued until the next song is done playing.

		This command automatically searches as well from YouTube.
		The list of supported sites can be found here:
		https://rg3.github.io/youtube-dl/supportedsites.html
		"""
		state = self.get_voice_state(ctx.message.server)
		opts = {
			'default_search': 'auto',
			'quiet': True,
		}

		if state.voice is None:
			success = await ctx.invoke(self.summon)
			if not success:
				return

		volume = self.settings.getServerStat(ctx.message.server, "Volume")
		defVolume = self.settings.getServerStat(ctx.message.server, "DefaultVolume")
		if volume:
			volume = float(volume)
		else:
			if defVolume:
				volume = float(self.settings.getServerStat(ctx.message.server, "DefaultVolume"))
			else:
				# No volume or default volume in settings - go with 60%
				volume = 0.6

		try:
			player = await state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
		except Exception as e:
			fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
			await self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
		else:
			player.volume = volume
			entry = VoiceEntry(ctx.message, player)
			await self.bot.say('Enqueued ' + str(entry))
			#await state.songs.put(entry)
			state.playlist.append(entry)

	@commands.command(pass_context=True, no_pm=True)
	async def volume(self, ctx, value : int):
		"""Sets the volume of the currently playing song."""

		state = self.get_voice_state(ctx.message.server)
		if state.is_playing():
			player = state.player
			if value < 0:
				value = 0
			if value > 100:
				value = 100
			player.volume = value / 100
			self.settings.setServerStat(ctx.message.server, "Volume", player.volume)
			await self.bot.say('Set the volume to {:.0%}'.format(player.volume))

	@commands.command(pass_context=True, no_pm=True)
	async def pause(self, ctx):
		"""Pauses the currently played song."""
		state = self.get_voice_state(ctx.message.server)
		if state.is_playing():
			player = state.player
			player.pause()
			state.total_playing_time += (datetime.datetime.now() - state.start_time)
			state.is_paused = True

	@commands.command(pass_context=True, no_pm=True)
	async def resume(self, ctx):
		"""Resumes the currently played song."""
		state = self.get_voice_state(ctx.message.server)
		if state.is_playing():
			player = state.player
			player.resume()
			state.start_time = datetime.datetime.now()
			state.is_paused = False


	@commands.command(pass_context=True, no_pm=True)
	async def stop(self, ctx):
		"""Stops playing audio and leaves the voice channel.

		This also clears the queue.
		"""

		channel = ctx.message.channel
		author  = ctx.message.author
		server  = ctx.message.server

		# Check for role requirements
		requiredRole = self.settings.getServerStat(server, "RequiredStopRole")
		if requiredRole == "":
			#admin only
			isAdmin = author.permissions_in(channel).administrator
			if not isAdmin:
				await self.bot.send_message(channel, 'You do not have sufficient privileges to access this command.')
				return
		else:
			#role requirement
			hasPerms = False
			for role in author.roles:
				if role.id == requiredRole:
					hasPerms = True
			if not hasPerms:
				await self.bot.send_message(channel, 'You do not have sufficient privileges to access this command.')
				return

		server = ctx.message.server
		state = self.get_voice_state(server)

		self.settings.setServerStat(ctx.message.server, "Volume", None)

		if state.is_playing():
			player = state.player
			player.stop()

		try:
			state.audio_player.cancel()
			del self.voice_states[server.id]
			state.playlist = []
			await state.voice.disconnect()
		except:
			pass

	@commands.command(pass_context=True, no_pm=True)
	async def skip(self, ctx):
		"""Vote to skip a song. The song requester can automatically skip."""

		state = self.get_voice_state(ctx.message.server)
		if not state.is_playing():
			await self.bot.say('Not playing anything right now...')
			return

		voter = ctx.message.author
		vote = await self.has_voted(ctx.message.author, state.votes)
		if vote != False:
			vote["value"] = 'skip'
		else:
			state.votes.append({ 'user': ctx.message.author, 'value': 'skip' })
		
		result = await self._vote_stats(ctx)

		if(result["total_skips"] >= result["total_keeps"]):
			await self.bot.say('Looks like skips WINS! sorry guys, skipping the song...')
			state.skip()
		# if voter == state.current.requester:
		# 	await self.bot.say('Requester requested skipping...')
		# 	state.skip()
		# elif voter.id not in state.skip_votes:
		# 	state.skip_votes.add(voter.id)
		# 	total_votes = len(state.skip_votes)
		# 	if total_votes >= 3:
		# 		await self.bot.say('Skip vote passed, skipping the song...')
		# 		state.skip()
		# 	else:
		# 		await self.bot.say('Skip vote added, currently at [{}/3]'.format(total_votes))
		# else:
		# 	await self.bot.say('You have already voted to skip this.')

	# @commands.command(pass_context=True, no_pm=True)
	# async def keep(self, ctx):
	# 	"""Vote to keep a song. The song requester can automatically skip.
	# 	"""

	@commands.command(pass_context=True, no_pm=True)
	async def keep(self, ctx):
		"""Vote to keep a song."""
		state = self.get_voice_state(ctx.message.server)
		if not state.is_playing():
			await self.bot.say('Not playing anything right now...')
			return

		voter = ctx.message.author
		vote = await self.has_voted(ctx.message.author, state.votes)
		if vote != False:
			vote["value"] = 'keep'
		else:
			state.votes.append({ 'user': ctx.message.author, 'value': 'keep' })
		
		await self._vote_stats(ctx)

	
	@commands.command(pass_context=True, no_pm=True)
	async def unvote(self, ctx):
		"""Remove your song vote."""
		state = self.get_voice_state(ctx.message.server)
		if not state.is_playing():
			await self.bot.say('Not playing anything right now...')
			return

		voter = ctx.message.author
		vote = await self.has_voted(ctx.message.author, state.votes)
		if vote != False:
			for voted in state.votes:
				if(ctx.message.author == voted["user"]):
					# Found our vote - remove it
					state.votes.remove(voted)
		else:
			await self.bot.say('Your non-existent vote has been removed.')

		result = await self._vote_stats(ctx)

		if(result["total_skips"] >= result["total_keeps"]):
			await self.bot.say('Looks like skips WINS! sorry guys, skipping the song...')
			state.skip()
		
	
	@commands.command(pass_context=True, no_pm=True)
	async def vote_stats(self, ctx):
		return await self._vote_stats(ctx)

	async def _vote_stats(self, ctx):
		state = self.get_voice_state(ctx.message.server)
		total_skips = 0
		total_keeps = 0
		for vote in state.votes:
			XP = self.settings.getUserStat(vote["user"], ctx.message.server, "XP")
			if vote["value"] == 'skip':
				total_skips = total_skips + XP
			else:
				total_keeps = total_keeps + XP
		
		await self.bot.say('**Total Votes**:\nKeeps Score: {}\nSkips Score : {}'.format(total_keeps, total_skips))

		return {'total_skips': total_skips, 'total_keeps': total_keeps}

	async def has_voted(self, user , votes):

		for vote in votes:
			if(user == vote["user"]):
				return vote

		return False


	@commands.command(pass_context=True, no_pm=True)
	async def playing(self, ctx):
		"""Shows info about currently playing."""

		state = self.get_voice_state(ctx.message.server)
		if not state.is_playing():
			await self.bot.say('Not playing anything.')
		else:
			diff_time = state.total_playing_time  + (datetime.datetime.now() - state.start_time)

			if state.is_paused:
				diff_time = state.total_playing_time

			seconds = diff_time.total_seconds()
			hours = seconds // 3600
			minutes = (seconds % 3600) // 60
			seconds = seconds % 60
			await self.bot.say('Now playing - {} [{:02d}:{:02d}:{:02d}]'.format(state.current,round(hours), round(minutes), round(seconds)))


	@commands.command(pass_context=True, no_pm=True)
	async def playlist(self, ctx):
		"""Shows current songs in the playlist."""
		state = self.get_voice_state(ctx.message.server)
		if len(state.playlist) <= 0:
						await self.bot.say('No songs in the playlist')
						return
		playlist_string  = '**Current PlayList**\n\n'
		#playlist_string += '```Markdown\n'
		count = 1
		for i in state.playlist:
						playlist_string += '{}. {}\n'.format(count, str(i))
						count = count + 1
		#playlist_string += '```'
		await self.bot.say(playlist_string)


	@commands.command(pass_context=True, no_pm=True)
	async def removesong(self, ctx, idx : int):
		"""Removes a song in the playlist by the index."""

		channel = ctx.message.channel
		author  = ctx.message.author
		server  = ctx.message.server

		# Check for role requirements
		requiredRole = self.settings.getServerStat(server, "RequiredStopRole")
		if requiredRole == "":
			#admin only
			isAdmin = author.permissions_in(channel).administrator
			if not isAdmin:
				await self.bot.send_message(channel, 'You do not have sufficient privileges to access this command.')
				return
		else:
			#role requirement
			hasPerms = False
			for role in author.roles:
				if role.id == requiredRole:
					hasPerms = True
			if not hasPerms:
				await self.bot.send_message(channel, 'You do not have sufficient privileges to access this command.')
				return

		if idx == None:
			await self.bot.say('Umm... Okay.  I successfully removed *0* songs from the playlist.  That\'s what you wanted, right?')
			return

		idx = idx - 1
		state = self.get_voice_state(ctx.message.server)
		if idx < 0 or idx >= len(state.playlist):
			await self.bot.say('Invalid song index, please refer to $playlist for the song index.')
			return
		song = state.playlist[idx]
		await self.bot.say('Deleted {} from playlist'.format(str(song)))
		if idx == 0:
			await self.bot.say('Cannot delete currently playing song, use $skip instead')
			return
		del state.playlist[idx]

import re
import os
import json5
import asyncio
import sqlite3
import hashlib
import platform
import collections

from enum import Enum
from threading import Lock
from telethon import TelegramClient, events
from telethon.tl.functions.messages import SendReactionRequest


class ProfileType(Enum):
	LIKING = 0
	DISLIKING = 1
	MISSED = 2


class ActionType(Enum):
	LIKE = 0
	DISLIKE = 1
	MISS = 2


class Profile:
	def __init__(self, text, typeId=None):
		self.text = text
		self.textHash = hashlib.md5(self.text.encode("utf-8")).digest()

		if isinstance(typeId, ProfileType):
			self.type = typeId
		else:
			self.setTypeFromId(typeId)

	def setTypeFromId(self, typeId):
		self.type = ProfileType(typeId) if not typeId is None else None


class App:
	def __init__(self):
		if os.name == "nt" and platform.version().startswith("10"):
			import win10toast
			self.toastNotifier = win10toast.ToastNotifier()
		else:
			self.toastNotifier = None

		self.connection = sqlite3.connect("profies.db", check_same_thread=False)
		with open("schema.sql", "r") as f:
			self.connection.executescript(f.read())

		self.dbLock = Lock()

		self.config = json5.load(open("config.json", encoding="utf-8"))
		self.spamPatterns = json5.load(open("spam.json", encoding="utf-8"))

		self.history = collections.deque(maxlen=10)

		self.bot = Bot(self, self.config["sessionFile"], self.config["apiId"], self.config["apiHash"])

	async def start(self):
		self.locationRegex = re.compile(f", 📍\d+ (km|км)")

		await self.bot.start()

	async def console(self):
		loop = asyncio.get_event_loop()
		while True:
			try:
				command, *args = (await loop.run_in_executor(None, input, "> ")).split(" ")

				if command in ("m", "miss", "missed"):
					index = 1

					try:
						if len(args) > 0:
							index = int(" ".join(args))

						await app.miss(index)

						if index == 0:
							await app._dislike()

					except ValueError:
						await app.missText(" ".join(args))

				elif command in ("exit", "stop"):
					os._exit(0)

				elif command in ("like", "l", "<3"):
					await app._like()

				elif command in ("dislike", "dis", "d"):
					await app._dislike()

				else:
					print("Unknown command")

			except Exception as e:
				print(e)

	async def getProfile(self, text):
		cursor = self.connection.cursor()
		profile = Profile(text)

		with self.dbLock:
			cursor.execute("SELECT type FROM profiles WHERE `hash` = ?", (profile.textHash,))
		
			profileTypeId = cursor.fetchone()

		if not profileTypeId is None:
			profile.setTypeFromId(profileTypeId[0])

		return profile

	async def addOrUpdateProfile(self, profile):
		cursor = self.connection.cursor()

		with self.dbLock:
			try:
				cursor.execute("INSERT OR REPLACE INTO profiles(hash, type) VALUES (?,?)", (profile.textHash, profile.type.value))
			except sqlite3.IntegrityError as e:
				print(f"Warn: {e}")

			self.connection.commit()

	async def miss(self, index):
		profile = self.history[-index - 1]
		profile = Profile(profile.text, ProfileType.MISSED)

		await self.addOrUpdateProfile(profile)

		print(f'Marked "{profile.text}" as missed')

	async def missText(self, text):
		profile = Profile(text, ProfileType.MISSED)

		await self.addOrUpdateProfile(profile)

		print(f'Marked "{profile.text}" as missed')

	# ----------------------------------------------------------------------------------------------

	async def onProfileRaw(self, text, reactionCallback):
		text = self.locationRegex.sub(f', {self.config["city"]}', text)

		profile = await self.getProfile(text)

		self.history.append(profile)

		print(f"Profile {profile.text}; {profile.type if not profile.type is None else 'New'}")

		reaction = None

		if profile.type == ProfileType.LIKING:
			action, reaction = self.config["onLiking"]["action"], self.config["onLiking"]["reaction"]
			
			if action == "dislike":
				await self._dislike()
			elif action == "like":
				await self._like()
			elif action == "alert":
				await self._alert("LIKING", "❤️")
			elif action == "pass":
				await self._pass()

		elif profile.type == ProfileType.DISLIKING:
			action, reaction = self.config["onDisliking"]["action"], self.config["onDisliking"]["reaction"]
			
			if action == "dislike":
				await self._dislike()
			elif action == "like":
				await self._like()
			elif action == "alert":
				await self._alert("DISLIKING", "👎")
			elif action == "pass":
				await self._pass()

		elif profile.type == ProfileType.MISSED:
			action, reaction = self.config["onMissed"]["action"], self.config["onMissed"]["reaction"]

			if action == "dislike":
				await self._dislike()
			elif action == "like":
				await self._like()
			elif action == "alert":
				await self._alert("MISSED", "👁‍🗨")
			elif action == "pass":
				await self._pass()	

		elif profile.type is None:
			action, reaction = self.config["onNew"]["action"], self.config["onNew"]["reaction"]
			
			if action == "dislike":
				await self._dislike()
			elif action == "like":
				await self._like()
			elif action == "alert":
				await self._alert("NEW", "➕")
			elif action == "pass":
				await self._pass()

		if not reaction is None:
			await reactionCallback(reaction)

	async def onAction(self, actionType):
		print(f"Action {actionType}")

		if len(self.history) == 0:
			print("Empty history")
			return

		profile = self.history[-1]

		if not profile.type in (None, ProfileType.MISSED):
			return

		if actionType == ActionType.LIKE:
			profile.type = ProfileType.LIKING
		elif actionType == ActionType.DISLIKE:
			profile.type = ProfileType.DISLIKING

		await self.addOrUpdateProfile(profile)

	async def onReaction(self, reaction, text, reactionCallback):
		if not self.config["reactionControls"]["enabled"]:
			return

		if reaction in (self.config["reactionControls"]["miss"], self.config["reactionControls"]["dislike"]):
			text = self.locationRegex.sub(f', {self.config["city"]}', text)
			profile = await self.getProfile(text)

			if reaction == self.config["reactionControls"]["miss"]:
				profile.type = ProfileType.MISSED
				print(f'Missed using reaction "{text}"')

			elif reaction == self.config["reactionControls"]["dislike"]:
				profile.type = ProfileType.DISLIKING
				print(f'Disliked using reaction "{text}"')
			
			await self.addOrUpdateProfile(profile)

			await asyncio.sleep(1)
			await reactionCallback(self.config["reactionControls"]["success"])
			await asyncio.sleep(1)
			await reactionCallback("")

	# ----------------------------------------------------------------------------------------------

	async def _like(self):
		await self.message("❤️")
			
		print("Action LIKE")

	async def _dislike(self):
		await self.message("👎")

		print("Action DISLIKE")

	async def _alert(self, title, text):
		if self.toastNotifier is not None:
			self.toastNotifier.show_toast(title, text, duration=5, threaded=True)
		
		print(f"Action ALERT {text}")

	async def _pass(self):
		print("Action PASS")

	# ----------------------------------------------------------------------------------------------

	async def message(self, message):
		await self.bot.client.send_message(self.config["chatId"], message)

	def checkSpam(self, message):
		for spamSubstring, spamReply in self.spamPatterns:
			if spamSubstring in message:
				return spamReply

		return None

class Bot:
	def __init__(self, app, sessionFile, apiId, apiHash):
		self.app = app

		self.sessionFile = sessionFile
		self.apiId = apiId
		self.apiHash = apiHash

		self.profileMessageRegex = re.compile(r"^.*, \d+, (\S+|📍\d+ km|📍\d+ км)( – .*|)$", re.S)

	async def start(self):
		self.client = TelegramClient(self.sessionFile, self.apiId, self.apiHash)
		await self.client.start()

		self._defineListeners()
		await self.app.console()

		await self.client.run_until_disconnected()

	async def _sendReaction(self, message, reaction):
		await self.client( SendReactionRequest(
			peer = message.peer_id,
			msg_id = message.id,
			reaction = reaction
		))

	def _defineListeners(self):
		@self.client.on(events.MessageEdited(chats=self.app.config["chatId"]))
		async def onMessageEdit(event):
			if not event.message.reactions.recent_reactions is None:
				reaction = event.message.reactions.recent_reactions[0].reaction
			else:
				reaction = ""

			await self.app.onReaction(
				reaction,
				event.message.message,
				lambda reaction: self._sendReaction(event.message, reaction)
			)
				
		@self.client.on(events.NewMessage(chats=self.app.config["chatId"]))
		async def onMessage(event):
			# Исходящие вообщения когда я чёто делаю
			if event.out:
				if event.message.message == "👎":
					await self.app.onAction(ActionType.DISLIKE)

				elif event.message.message == "❤️":
					await self.app.onAction(ActionType.LIKE)

			# Входящее
			else:
				# Если это сообщение с анкетой, чекаем регуляркой
				if self.profileMessageRegex.match(event.message.message):
					await self.app.onProfileRaw(event.message.message, lambda reaction: self._sendReaction(event.message, reaction))

				# Если пришло такое сообщение это значит я перед этим отправил лайк с сообщением, типа тоже исходящий лайк ивент вот да
				elif event.message.message == "Лайк отправлен, ждем ответа.":
					await self.app.onAction(ActionType.LIKE)

				# Чекаем что если сообщение это спам
				else:
					spamReply = self.app.checkSpam(event.message.message)
					if not spamReply is None:
						await self.app.message(spamReply)

app = App()
asyncio.run(app.start())
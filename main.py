import re
import os
import sqlite3
import hashlib
import json5
import collections
import asyncio

from threading import Thread, Lock
from enum import Enum
from telethon import TelegramClient, events

class ProfileType(Enum):
	LIKING = 0
	DISLIKING = 1
	MISSED = 2

class ReactionType(Enum):
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
		if os.name == "nt":
			import win10toast
			self.toastNotifier = win10toast.ToastNotifier()

		self.connection = sqlite3.connect("profies.db", check_same_thread=False)
		with open("schema.sql", "r") as f:
			self.connection.executescript(f.read())

		self.dbLock = Lock()

		self.config = json5.load(open("config.json"))
		self.spamPatterns = json5.load(open("spam.json"))

		self.history = collections.deque(maxlen=10)

		self.bot = Bot(self, self.config["sessionFile"], self.config["apiId"], self.config["apiHash"])

	async def start(self):
		await self.bot.start()

	async def console(self):
		loop = asyncio.get_event_loop()
		while True:
			try:
				command, *args = (await loop.run_in_executor(None, input, "> ")).split(" ")

				if command in ("miss", "missed"):
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

				elif command == "like":
					await app._like()

				elif command == "dislike":
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

	async def addProfile(self, profile):
		cursor = self.connection.cursor()

		with self.dbLock:
			try:
				cursor.execute("INSERT INTO profiles(hash,type) VALUES (?,?)", (profile.textHash, profile.type.value))
			except sqlite3.IntegrityError as e:
				print(f"Warn: {e}")

			self.connection.commit()

	async def miss(self, index):
		profile = self.history[-index - 1]
		cursor = self.connection.cursor()
		
		with self.dbLock:
			cursor.execute("UPDATE profiles SET type=? WHERE hash=?", (ProfileType.MISSED.value, profile.textHash))
			self.connection.commit()

		print(f'Marked "{profile.text}" as missed')

	async def missText(self, text):
		profile = Profile(text, ProfileType.MISSED)
		cursor = self.connection.cursor()

		with self.dbLock:
			cursor.execute("INSERT OR REPLACE INTO profiles(hash, type) VALUES (?,?)", (profile.textHash, profile.type.value))
			self.connection.commit()

		print(f'Marked "{profile.text}" as missed')

	# ----------------------------------------------------------------------------------------------

	async def onProfileRaw(self, text):
		profile = await self.getProfile(text)

		self.history.append(profile)

		print(f"Profile {profile.text}; {profile.type if not profile.type is None else 'New'}")

		if profile.type == ProfileType.LIKING:
			if self.config["onLiking"] == "dislike":
				await self._dislike()
			elif self.config["onLiking"] == "like":
				await self._like()
			elif self.config["onLiking"] == "alert":
				await self._alert("LIKING", "❤️")
			elif self.config["onLiking"] == "pass":
				await self._pass()

		elif profile.type == ProfileType.DISLIKING:
			if self.config["onDisliking"] == "dislike":
				await self._dislike()
			elif self.config["onDisliking"] == "like":
				await self._like()
			elif self.config["onDisliking"] == "alert":
				await self._alert("DISLIKING", "👎")
			elif self.config["onDisliking"] == "pass":
				await self._pass()

		elif profile.type == ProfileType.MISSED:
			if self.config["onMissed"] == "dislike":
				await self._dislike()
			elif self.config["onMissed"] == "like":
				await self._like()
			elif self.config["onMissed"] == "alert":
				await self._alert("MISSED", "👁‍🗨")
			elif self.config["onMissed"] == "pass":
				await self._pass()	

		elif profile.type is None:
			if self.config["onNew"] == "dislike":
				await self._dislike()
			elif self.config["onNew"] == "like":
				await self._like()
			elif self.config["onNew"] == "alert":
				await self._alert("NEW", "➕")
			elif self.config["onNew"] == "pass":
				await self._pass()	

	async def onReaction(self, reactionType):
		print(f"Reaction {reactionType}")

		if len(self.history) == 0:
			print("Empty history")
			return

		profile = self.history[-1]

		if not profile.type in (None, ProfileType.MISSED):
			return

		if reactionType == ReactionType.LIKE:
			profile.type = ProfileType.LIKING
		elif reactionType == ReactionType.DISLIKE:
			profile.type = ProfileType.DISLIKING

		await self.addProfile(profile)

	# ----------------------------------------------------------------------------------------------

	async def _like(self):
		await self.message("❤️")
			
		print("Action LIKE")

	async def _dislike(self):
		await self.message("👎")

		print("Action DISLIKE")

	async def _alert(self, title, text):
		if os.name == "nt":
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

		self.profileMessageRegex = re.compile(r"^.*, \d+, \S+( – .*|)$", re.S)

	async def start(self):
		self.client = TelegramClient(self.sessionFile, self.apiId, self.apiHash)
		await self.client.start()

		self._defineListeners()
		await self.app.console()

		await self.client.run_until_disconnected()

	def _defineListeners(self):
		@self.client.on(events.NewMessage(chats=self.app.config["chatId"]))
		async def onMessage(event):
			# Исходящие вообщения когда я чёто делаю
			if event.out:
				if event.message.message == "👎":
					await self.app.onReaction(ReactionType.DISLIKE)

				elif event.message.message == "❤️":
					await self.app.onReaction(ReactionType.LIKE)

			# Входящее
			else:
				# Если это сообщение с анкетой, чекаем регуляркой
				if self.profileMessageRegex.match(event.message.message):
					await self.app.onProfileRaw(event.message.message)

				# Если пришло такое сообщение это значит я перед этим отправил лайк с сообщением, типа тоже исходящий лайк ивент вот да
				elif event.message.message == "Лайк отправлен, ждем ответа.":
					await self.app.onReaction(ReactionType.LIKE)

				# Чекаем что если сообщение это спам
				else:
					spamReply = self.app.checkSpam(event.message.message)
					if not spamReply is None:
						await self.app.message(spamReply)

app = App()
asyncio.run(app.start())
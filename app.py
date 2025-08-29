from typing import Callable
import collections
import threading
import platform
import asyncio
import sqlite3
import os
import re

import json5 # type: ignore

from bot import Bot
from datatypes import ActionType, Profile, ProfileType


class App:
	DATABASE_FILEPATH = "./profiles.db"

	def __init__(self) -> None:
		if os.name == "nt" and platform.version().startswith("10"):
			import win10toast # type: ignore
			self.toastNotifier = win10toast.ToastNotifier()
		else:
			self.toastNotifier = None

		# backward compatibility with a typo
		if os.path.isfile("profies.db"):
			self.DATABASE_FILEPATH = "profies.db"

		self.connection = sqlite3.connect(self.DATABASE_FILEPATH, check_same_thread=False)
		with open("schema.sql", "r") as f:
			self.connection.executescript(f.read())

		self.dbLock = threading.Lock()

		self.config = json5.load(open("config.json", encoding="utf-8"))
		self.spamPatterns = json5.load(open("spam.json", encoding="utf-8"))

		self.history: collections.deque[Profile] = collections.deque(maxlen=10)

		self.bot = Bot(self, self.config["sessionFile"])

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

						await self.miss(index)

						if index == 0:
							await self._dislike()

					except ValueError:
						await self.missText(" ".join(args))

				elif command in ("exit", "stop"):
					os._exit(0)

				elif command in ("like", "l", "<3"):
					await self._like()

				elif command in ("dislike", "dis", "d"):
					await self._dislike()

				else:
					print("Unknown command")

			except Exception as e:
				print(e)

	async def getProfile(self, text: str):
		cursor = self.connection.cursor()
		profile = Profile(text)

		with self.dbLock:
			cursor.execute("SELECT type FROM profiles WHERE `hash` = ?", (profile.textHash,))
		
			profileTypeId = cursor.fetchone()

		if not profileTypeId is None:
			profile.setTypeFromId(profileTypeId[0])

		return profile

	async def addOrUpdateProfile(self, profile: Profile):
		cursor = self.connection.cursor()

		with self.dbLock:
			try:
				cursor.execute("INSERT OR REPLACE INTO profiles(hash, type) VALUES (?,?)", (profile.textHash, profile.type.value))
			except sqlite3.IntegrityError as e:
				print(f"Warn: {e}")

			self.connection.commit()

	async def miss(self, index: int):
		profile = self.history[-index - 1]
		profile = Profile(profile.text, ProfileType.MISSED)

		await self.addOrUpdateProfile(profile)

		print(f'Marked "{profile.text}" as missed')

	async def missText(self, text: str):
		profile = Profile(text, ProfileType.MISSED)

		await self.addOrUpdateProfile(profile)

		print(f'Marked "{profile.text}" as missed')

	# ----------------------------------------------------------------------------------------------

	async def onProfileRaw(self, text: str, reactionCallback: Callable):
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

	async def onAction(self, actionType: ActionType):
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

	async def onReaction(self, reaction: str, text: str, reactionCallback: Callable):
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
			await reactionCallback(None)

	# ----------------------------------------------------------------------------------------------

	async def _like(self):
		await self.message("❤️")
			
		print("Action LIKE")

	async def _dislike(self):
		await self.message("👎")

		print("Action DISLIKE")

	async def _alert(self, title: str, text: str):
		if self.toastNotifier is not None:
			self.toastNotifier.show_toast(title, text, duration=5, threaded=True)
		
		print(f"Action ALERT {text}")

	async def _pass(self):
		print("Action PASS")

	# ----------------------------------------------------------------------------------------------

	async def message(self, message: str):
		await self.bot.client.send_message(self.config["chatId"], message)

	def checkSpam(self, message: str):
		for spamSubstring, spamReply in self.spamPatterns:
			if spamSubstring in message:
				return spamReply

		return None
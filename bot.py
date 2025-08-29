import os
import re

from telethon import events # type: ignore
from telethon.tl.functions.messages import SendReactionRequest # type: ignore
from telethon.types import Message, ReactionEmoji, ReactionEmpty # type: ignore
from opentele.tl import TelegramClient # type: ignore
from opentele.api import API # type: ignore

from datatypes import ActionType
import app


class Bot:
	def __init__(self, app: 'app.App', sessionFile: str):
		self.app = app

		self.sessionFile = sessionFile

		self.profileMessageRegex = re.compile(r"^.*, \d+, (\S+|📍\d+ km|📍\d+ км)( – .*|)$", re.S)

	async def start(self):
		os.makedirs(os.path.dirname(self.sessionFile), exist_ok=True)

		self.client = TelegramClient(self.sessionFile,
			api = API.TelegramDesktop(
				app_version="6.0.2 x64"
			)
		)
		await self.client.start()

		self._defineListeners()
		await self.app.console()

		await self.client.run_until_disconnected()

	async def _sendReaction(self, message: Message, emoticon: str):
		if emoticon is None:
			reaction = ReactionEmpty()
		else:
			reaction = ReactionEmoji(emoticon)

		await self.client( SendReactionRequest(
			peer = message.peer_id,
			msg_id = message.id,
			reaction = [reaction]
		))

	def _defineListeners(self):
		@self.client.on(events.MessageEdited(chats=self.app.config["chatId"]))
		async def onMessageEdit(event: events.MessageEdited.Event):
			if not event.message.reactions.recent_reactions is None:
				emoticon = event.message.reactions.recent_reactions[0].reaction.emoticon
			else:
				emoticon = None

			await self.app.onReaction(
				emoticon,
				event.message.message,
				lambda emoticon: self._sendReaction(event.message, emoticon)
			)
				
		@self.client.on(events.NewMessage(chats=self.app.config["chatId"]))
		async def onMessage(event: events.NewMessage.Event):
			# Исходящие сообщения когда я чёто делаю
			if event.out:
				if event.message.message == "👎":
					await self.app.onAction(ActionType.DISLIKE)

				elif event.message.message == "❤️":
					await self.app.onAction(ActionType.LIKE)

			# Входящее
			else:
				# Если это сообщение с анкетой, чекаем регуляркой
				if self.profileMessageRegex.match(event.message.message):
					await self.app.onProfileRaw(event.message.message, lambda emoticon: self._sendReaction(event.message, emoticon))

				# Если пришло такое сообщение это значит я перед этим отправил лайк с сообщением, типа тоже исходящий лайк ивент вот да
				elif event.message.message == "Лайк отправлен, ждем ответа.":
					await self.app.onAction(ActionType.LIKE)

				# Чекаем что если сообщение это спам
				else:
					spamReply = self.app.checkSpam(event.message.message)
					if not spamReply is None:
						await self.app.message(spamReply)
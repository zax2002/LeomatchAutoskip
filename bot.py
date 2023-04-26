import re

from telethon import TelegramClient, events
from telethon.types import Message, ReactionEmoji
from telethon.tl.functions.messages import SendReactionRequest

from datatypes import ActionType
import app


class Bot:
	def __init__(self, app: 'app.App', sessionFile: str, apiId: int, apiHash: str):
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

	async def _sendReaction(self, message: Message, reaction: str):
		await self.client( SendReactionRequest(
			peer = message.peer_id,
			msg_id = message.id,
			reaction = [ReactionEmoji(reaction)]
		))

	def _defineListeners(self):
		@self.client.on(events.MessageEdited(chats=self.app.config["chatId"]))
		async def onMessageEdit(event: events.MessageEdited.Event):
			if not event.message.reactions.recent_reactions is None:
				reaction = event.message.reactions.recent_reactions[0].reaction.emoticon
			else:
				reaction = ""

			await self.app.onReaction(
				reaction,
				event.message.message,
				lambda reaction: self._sendReaction(event.message, reaction)
			)
				
		@self.client.on(events.NewMessage(chats=self.app.config["chatId"]))
		async def onMessage(event: events.NewMessage.Event):
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
from enum import Enum
import hashlib


class ProfileType(Enum):
	LIKING = 0
	DISLIKING = 1
	MISSED = 2


class ActionType(Enum):
	LIKE = 0
	DISLIKE = 1
	MISS = 2


class Profile:
	def __init__(self, text: str, typeId: ProfileType | int = None):
		self.text = text
		self.textHash = hashlib.md5(self.text.encode("utf-8")).digest()

		if isinstance(typeId, ProfileType):
			self.type = typeId
		else:
			self.setTypeFromId(typeId)

	def setTypeFromId(self, typeId: int):
		self.type = ProfileType(typeId) if not typeId is None else None
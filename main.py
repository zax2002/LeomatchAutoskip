import asyncio

from app import App


def main():
	app = App()
	asyncio.run(app.start())

if __name__ == "__main__":
	main()
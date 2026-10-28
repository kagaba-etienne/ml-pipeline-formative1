from dotenv import load_dotenv
from generated.mongo_client import Prisma as MongoPrisma
from generated.mysql_client import Prisma as MySQLPrisma

load_dotenv()

mysql_client = MySQLPrisma()
mongo_client = MongoPrisma()

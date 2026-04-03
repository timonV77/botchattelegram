import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def test_connection():
    print("Testing PostgreSQL connection...")
    print(f"Host: {os.getenv('DB_HOST')}")
    print(f"Port: {os.getenv('DB_PORT')}")
    print(f"Database: {os.getenv('DB_NAME')}")
    print(f"User: {os.getenv('DB_USER')}")
    print()
    
    # Try with provided credentials
    try:
        conn = await asyncpg.connect(
            host=os.getenv('DB_HOST', '127.0.0.1'),
            port=int(os.getenv('DB_PORT', 5432)),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASS'),
            database=os.getenv('DB_NAME'),
            timeout=5
        )
        print("✅ Connection with bot_user successful!")
        await conn.close()
        return True
    except Exception as e:
        print(f"❌ Connection failed: {type(e).__name__}")
        print(f"Error: {e}")
        print()
        
        # Try as postgres superuser
        print("Trying as postgres superuser...")
        try:
            conn = await asyncpg.connect(
                host='127.0.0.1',
                port=5432,
                user='postgres',
                password='postgres',
                timeout=5
            )
            print("✅ Connected as postgres superuser")
            
            # Check databases
            dbs = await conn.fetch("SELECT datname FROM pg_database WHERE datname IN ('bot_db', 'template1')")
            print(f"Databases: {[db['datname'] for db in dbs]}")
            
            # Check users
            users = await conn.fetch("SELECT usename FROM pg_user WHERE usename IN ('bot_user', 'postgres')")
            print(f"Users: {[u['usename'] for u in users]}")
            
            await conn.close()
            return False
        except Exception as e2:
            print(f"Also failed: {e2}")
            return False

asyncio.run(test_connection())

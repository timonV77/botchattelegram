import sys

try:
    with open('app/vk/handlers.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Apply global replacement
    content = content.replace('get_main_keyboard()', 'get_main_keyboard(user_id)')
    
    # Fix handle_help
    old_help = '''    async def handle_help(self, message: Message) -> str:
        """Show help"""
        help_text'''
    new_help = '''    async def handle_help(self, message: Message) -> str:
        """Show help"""
        user_id = message.from_id
        help_text'''
    content = content.replace(old_help, new_help)

    with open('app/vk/handlers.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {e}")

import asyncio
import os
from vkbottle import API
from vkbottle import VideoUploader
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("VK_TOKEN")
api = API(token=token)

async def main():
    # create dummy mp4
    with open("dummy.mp4", "wb") as f:
        # write a valid tiny mp4 header so VK accepts it as video
        import base64
        tiny_mp4 = base64.b64decode("AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAAALFtZGF0AAACrgYF//+//7/1AIf/gH/9//+AAEAAABoEAcIAAAABgD//wAAAAABAAAABwAAAMgYAAAAAA=")
        f.write(tiny_mp4)
        
    try:
        uploader = VideoUploader(api)
        print("Uploading dummy video...")
        attachment = await uploader.upload("dummy.mp4", name="Test Video")
        
        print("Uploaded! Attachment:", attachment)
        
        video_id = attachment.replace("video", "")
        print("Fetching video info for", video_id)
        res = await api.video.get(videos=[video_id])
        if res and res.items:
            video_obj = res.items[0]
            print("Video Title:", video_obj.title)
            if hasattr(video_obj, "files") and video_obj.files:
                print("Direct files found!")
                for qual, url in video_obj.files.dict().items():
                    if url:
                        print(f"- {qual}: {url}")
            else:
                print("No 'files' field in video object :(")
                print("Available fields:", video_obj.dict().keys())
                print("Player URL:", video_obj.player)
    
    except Exception as e:
        print("Error:", e)
        
if __name__ == "__main__":
    asyncio.run(main())

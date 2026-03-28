import discord
from discord.ext import commands, tasks
import aiohttp
import json
import re
import os
import html
import datetime
from datetime import time, timezone, timedelta
import random
import traceback

# ================= [ 설정 구역 ] =================
# 환경 변수에서 키를 가져옵니다.
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# 채널 ID 설정
NEWS_CHANNEL_ID = 1480944831600656384  
VOTE_CHANNEL_ID = 1484797598241128598  
YT_NOTI_CHANNEL_ID = 1487481812874825879

# 타임존 및 스케줄 설정 (KST)
KST = timezone(timedelta(hours=9))
SCHEDULED_VOTE_TIME = time(hour=13, minute=0, second=0, tzinfo=KST)

# 티어 데이터
TIER_DATA = {
    "Challenger": 0xf4c874, "Grandmaster": 0xc64444, "Master": 0x9d5ca3,
    "Diamond": 0x576bce, "Emerald": 0x2da161, "Platinum": 0x4e9996,
    "Gold": 0xcd8837, "Silver": 0x80989d, "Bronze": 0x8c513a,
    "Iron": 0x51484a, "Unranked": 0x000000
}
TIER_LIST = list(TIER_DATA.keys())

pending_users = {}

# [로그 설정]
def log(message):
    now = datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {message}", flush=True)

# ================= [ 봇 클래스 정의 ] =================
class LoLBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True 
        super().__init__(command_prefix='!', intents=intents)
        self.session = None

    async def setup_hook(self):
        # 전역 세션 생성 (모든 API 호출에 재사용)
        self.session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        })
        log("공용 HTTP 세션 생성 및 봇 준비 완료")
        
    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

bot = LoLBot()

# ================= [ 공통 유틸리티 함수 ] =================
async def get_puuid(name_with_tag):
    """라이엇 ID를 입력받아 PUUID를 반환 (실패 시 None)"""
    if "#" not in name_with_tag: return None
    try:
        name, tag = name_with_tag.split("#", 1)
        url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name.strip()}/{tag.strip()}?api_key={RIOT_API_KEY}"
        async with bot.session.get(url) as resp:
            if resp.status == 200:
                return (await resp.json()).get('puuid')
    except Exception as e:
        log(f"PUUID 조회 에러: {e}")
    return None

async def is_already_posted(channel, target_url):
    """채널 최근 히스토리에서 동일한 URL의 임베드가 있는지 확인"""
    async for msg in channel.history(limit=10): # 최근 10개만 확인해도 충분
        if msg.author == bot.user and msg.embeds and msg.embeds[0].url == target_url:
            return True
    return False

# ================= [ 핵심 기능: 뉴스 & 유튜브 ] =================
async def fetch_and_post_news():
    log("롤 뉴스 체크 중...")
    url = "https://www.leagueoflegends.com/ko-kr/news/"
    try:
        async with bot.session.get(url) as resp:
            if resp.status != 200: return
            raw_html = await resp.text()
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw_html)
            if not match: return
            
            data = json.loads(match.group(1))
            blades = data.get('props', {}).get('pageProps', {}).get('page', {}).get('blades', [])
            articles = next((b['items'] for b in blades if b.get('type') == 'articleCardGrid'), [])[:10]
            articles.reverse()

            channel = await bot.fetch_channel(NEWS_CHANNEL_ID)
            for art in articles:
                link = art.get('action', {}).get('payload', {}).get('url', '')
                if not link: continue
                if not link.startswith('http'): link = "https://www.leagueoflegends.com" + link
                
                if await is_already_posted(channel, link): continue

                title = art.get('title', '새로운 소식')
                desc = re.sub(r'<[^>]+>', '', art.get('description', {}).get('body', '')).strip()
                img = html.unescape(art.get('media', {}).get('url', '')).strip()
                
                # 날짜 처리
                pub = art.get('publishedAt', '')
                date_text = "새 소식"
                if pub:
                    dt = datetime.datetime.fromisoformat(pub.replace('Z', '+00:00')).astimezone(KST)
                    date_text = dt.strftime("%Y년 %m월 %d일 %H:%M")

                embed = discord.Embed(title=title, url=link, description=desc[:100], color=0xFFFFFF)
                if img.startswith('http'): embed.set_image(url=img)
                embed.set_footer(text=date_text)
                await channel.send(embed=embed)
                log(f"뉴스 포스팅: {title}")
    except Exception as e: log(f"뉴스 에러: {e}")

async def fetch_and_post_youtube():
    log("유튜브 영상 체크 중...")
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId=UC7S_G_miz2fS9a4m_1uUvSg&part=snippet,id&order=date&maxResults=10&type=video"
    try:
        async with bot.session.get(url) as resp:
            if resp.status != 200: return
            videos = (await resp.json()).get('items', [])
            videos.reverse()

            channel = await bot.fetch_channel(YT_NOTI_CHANNEL_ID)
            for vid in videos:
                v_id = vid['id']['videoId']
                v_url = f"https://www.youtube.com/watch?v={v_id}"
                
                if await is_already_posted(channel, v_url): continue

                title = html.unescape(vid['snippet']['title'])
                desc = vid['snippet']['description'][:100] + "..."
                img = vid['snippet']['thumbnails']['high']['url']
                dt = datetime.datetime.fromisoformat(vid['snippet']['publishedAt'].replace('Z', '+00:00')).astimezone(KST)

                embed = discord.Embed(title=title, url=v_url, description=desc, color=0xFF0000)
                embed.set_image(url=img)
                embed.set_footer(text=f"YouTube 업로드 • {dt.strftime('%Y년 %m월 %d일 %H:%M')}")
                await channel.send(embed=embed)
                log(f"유튜브 포스팅: {title}")
    except Exception as e: log(f"유튜브 에러: {e}")

# ================= [ 자동 루프 & 이벤트 ] =================
@tasks.loop(minutes=60)
async def main_loop():
    await fetch_and_post_news()
    await fetch_and_post_youtube()

@tasks.loop(time=SCHEDULED_VOTE_TIME)
async def daily_vote_loop():
    try:
        channel = await bot.fetch_channel(VOTE_CHANNEL_ID)
        date_str = datetime.datetime.now(KST).strftime("%Y년 %m월 %d일")
        poll = discord.Poll(question=f"🎮 {date_str} 오늘 게임하실 건가요? (포지션 선택)", duration=timedelta(hours=11))
        for t, e in [("TOP", "🛡️"), ("JGL", "⚔️"), ("MID", "🔥"), ("SUP", "✨"), ("ADC", "🏹"), ("미정", "❓"), ("불참", "❌")]:
            poll.add_answer(text=t, emoji=e)
        await channel.send(poll=poll)
        log(f"투표 게시 완료 ({date_str})")
    except Exception as e: log(f"투표 에러: {e}")

@bot.event
async def on_ready():
    log(f"봇 로그인: {bot.user.name}")
    if not main_loop.is_running(): main_loop.start()
    if not daily_vote_loop.is_running(): daily_vote_loop.start()

# ================= [ 명령어 구역 ] =================
@bot.command()
async def 인증(ctx, *, name=None):
    if not name or "#" not in name:
        return await ctx.send("❌ 사용법: `!인증 소환사명#태그`")
    
    icon_id = random.randint(0, 28)
    pending_users[ctx.author.id] = {"name": name, "icon": icon_id}
    url = f"https://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{icon_id}.png"
    
    embed = discord.Embed(title="🛡️ 계정 인증", description=f"**{name}**님, 아이콘을 변경 후 `!확인`을 입력하세요.", color=0x5865F2)
    embed.set_thumbnail(url=url)
    await ctx.send(embed=embed)

@bot.command()
async def 확인(ctx):
    user = pending_users.get(ctx.author.id)
    if not user: return await ctx.send("❌ 먼저 `!인증`을 해주세요.")
    
    puuid = await get_puuid(user["name"])
    if not puuid: return await ctx.send("❌ 계정을 찾을 수 없습니다.")

    async with bot.session.get(f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_API_KEY}") as r:
        if r.status == 200 and (await r.json()).get('profileIconId') == user["icon"]:
            await ctx.send(f"✅ 인증 성공! 이제 `!갱신 {user['name']}`을 입력하세요.")
            del pending_users[ctx.author.id]
        else:
            await ctx.send("❌ 아이콘이 일치하지 않습니다.")

@bot.command()
async def 갱신(ctx, *, name=None):
    if not name or "#" not in name: return await ctx.send("❌ 사용법: `!갱신 소환사명#태그`")
    
    puuid = await get_puuid(name)
    if not puuid: return await ctx.send("❌ 계정을 찾을 수 없습니다.")

    async with bot.session.get(f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={RIOT_API_KEY}") as r:
        if r.status == 200:
            data = await r.json()
            tier = next((e['tier'] for e in data if e['queueType'] == 'RANKED_SOLO_5x5'), "Unranked").capitalize()
            role = discord.utils.get(ctx.guild.roles, name=tier)
            
            if not role: return await ctx.send(f"❌ '{tier}' 역할이 서버에 없습니다.")
            
            await ctx.author.remove_roles(*[r for r in ctx.author.roles if r.name in TIER_LIST])
            await ctx.author.add_roles(role)
            await ctx.send(f"🔄 **{ctx.author.display_name}**님, **{tier}** 갱신 완료!")

bot.run(DISCORD_TOKEN)

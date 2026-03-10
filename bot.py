import discord
from discord.ext import commands, tasks
import aiohttp
from bs4 import BeautifulSoup
import random
import traceback
import os
import asyncio

# ================= [ 설정 구역 ] =================
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# 📢 새소식을 보낼 채널 ID (반드시 본인 서버의 채널 ID로 수정)
NEWS_CHANNEL_ID = 1480944831600656384

TIER_DATA = {
    "Challenger": 0xf4c874, "Grandmaster": 0xc64444, "Master": 0x9d5ca3,
    "Diamond": 0x576bce, "Emerald": 0x2da161, "Platinum": 0x4e9996,
    "Gold": 0xcd8837, "Silver": 0x80989d, "Bronze": 0x8c513a,
    "Iron": 0x51484a, "Unranked": 0x000000
}
TIER_LIST = list(TIER_DATA.keys())
# ===============================================

# [개선] Intents를 필요한 것만 켜서 봇의 부하를 줄입니다.
intents = discord.Intents.default()
intents.message_content = True
intents.members = True 

bot = commands.Bot(command_prefix='!', intents=intents)
pending_users = {}

# --- [ 신규 기능: 롤 새소식 크롤링 루프 ] ---
@tasks.loop(minutes=60)
async def check_lol_news():
    print("--- [로그] 뉴스 체크 루프 시작 ---")
    url = "https://www.leagueoflegends.com/ko-kr/news/latest/"
    
    async with aiohttp.ClientSession() as session:
        try:
            # fetch_channel을 사용하여 채널 정보를 강제로 새로고침합니다.
            channel = await bot.fetch_channel(NEWS_CHANNEL_ID)
            
            async with session.get(url) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # 뉴스 카드 추출
                    articles = soup.select('a[data-testid^="article-card-"]')[:10]
                    articles.reverse() 
                    
                    # 채널 히스토리에서 이미 올린 뉴스 제목들 수집
                    already_posted_titles = []
                    async for message in channel.history(limit=100):
                        if message.author == bot.user and message.embeds:
                            # 임베드 설명창의 **제목** 부분 추출
                            clean_title = message.embeds[0].description.replace("**", "").strip()
                            already_posted_titles.append(clean_title)

                    new_count = 0
                    for article in articles:
                        title_element = article.find('h2')
                        if not title_element: continue
                        
                        title = title_element.text.strip()
                        link = "https://www.leagueoflegends.com" + article['href']
                        
                        # 중복 검사
                        if title in already_posted_titles:
                            continue
                        
                        embed = discord.Embed(
                            title="🆕 롤 공식 홈페이지 소식",
                            description=f"**{title}**",
                            url=link,
                            color=0x0066ff
                        )
                        embed.set_footer(text="League of Legends News Feed")
                        await channel.send(embed=embed)
                        new_count += 1
                        print(f"--- [로그] 뉴스 전송 완료: {title} ---")
                    
                    if new_count == 0:
                        print("--- [로그] 새로운 뉴스가 없습니다. ---")
        except Exception as e:
            print(f"--- [로그] 뉴스 루프 에러 발생: {e} ---")

@bot.event
async def on_ready():
    print(f"--- [로그] 로그인 성공: {bot.user.name} ---")
    # 뉴스 체크 루프 시작 (중복 실행 방지)
    if not check_lol_news.is_running():
        check_lol_news.start()
        print("--- [로그] 뉴스 체크 루프가 가동되었습니다! ---")

# --- [ 기존 기능: 서버 입장 시 역할 자동 생성 ] ---
@bot.event
async def on_guild_join(guild):
    print(f"--- [로그] 새로운 서버 입장: {guild.name} ---")
    for role_name, color_hex in TIER_DATA.items():
        if not discord.utils.get(guild.roles, name=role_name):
            try:
                await guild.create_role(name=role_name, color=discord.Color(color_hex), hoist=True)
            except discord.Forbidden:
                print(f"--- [로그] {guild.name} 서버: 역할 생성 권한 없음 ---")
                break

# --- [ 기존 기능: 인증 및 갱신 ] ---
@bot.command()
async def 인증(ctx, *, summoner_name):
    if "#" not in summoner_name:
        await ctx.send("❌ 소환사명 뒤에 태그(#)를 포함해 주세요. (예: 페이커#KR1)")
        return
    
    target_icon = random.randint(0, 28)
    pending_users[ctx.author.id] = {"name": summoner_name, "icon": target_icon}
    
    icon_url = f"https://ddragon.leagueoflegends.com/cdn/14.1.1/img/profileicon/{target_icon}.png"
    embed = discord.Embed(
        title="🛡️ 롤 계정 소유권 인증", 
        description=f"**{summoner_name}**님, 본인 확인을 위해\n프로필 아이콘을 아래 이미지로 변경한 후 `!확인`을 입력하세요.", 
        color=0x5865F2
    )
    embed.set_thumbnail(url=icon_url)
    await ctx.send(embed=embed)

@bot.command()
async def 확인(ctx):
    if ctx.author.id not in pending_users:
        await ctx.send("먼저 `!인증 소환사명#태그`를 입력해 인증을 시작하세요.")
        return

    user_info = pending_users[ctx.author.id]
    name, tag = user_info["name"].split("#")
    
    async with aiohttp.ClientSession() as session:
        try:
            acc_url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_API_KEY}"
            async with session.get(acc_url) as r1:
                acc_data = await r1.json()
                puuid = acc_data.get('puuid')
                if not puuid:
                    await ctx.send("❌ 라이엇 계정 정보를 찾을 수 없습니다.")
                    return

            sum_url = f"https://kr.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}?api_key={RIOT_API_KEY}"
            async with session.get(sum_url) as r2:
                sum_data = await r2.json()
                current_icon = sum_data.get('profileIconId')

            if current_icon == user_info["icon"]:
                await ctx.send(f"✅ **{user_info['name']}**님, 인증 성공!\n이제 `!갱신 {user_info['name']}`을 입력하세요.")
                del pending_users[ctx.author.id]
            else:
                await ctx.send(f"❌ 아이콘 불일치. (현재: {current_icon} / 목표: {user_info['icon']})")
        except Exception:
            await ctx.send("오류 발생. API 키를 확인하세요.")

@bot.command()
async def 갱신(ctx, *, summoner_name):
    if "#" not in summoner_name:
        await ctx.send("❌ `!갱신 소환사명#태그` 형식으로 입력해주세요.")
        return

    name, tag = summoner_name.split("#")
    async with aiohttp.ClientSession() as session:
        try:
            acc_url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{name}/{tag}?api_key={RIOT_API_KEY}"
            async with session.get(acc_url) as r1:
                acc_data = await r1.json()
                puuid = acc_data.get('puuid')
            
            league_url = f"https://kr.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}?api_key={RIOT_API_KEY}"
            async with session.get(league_url) as r2:
                league_data = await r2.json()
                
                user_tier = "UNRANKED"
                for entry in league_data:
                    if entry['queueType'] == 'RANKED_SOLO_5x5':
                        user_tier = entry['tier']
                        break
                
                role_name = user_tier.capitalize()
                new_role = discord.utils.get(ctx.guild.roles, name=role_name)

                if not new_role:
                    await ctx.send(f"❌ '{role_name}' 역할이 서버에 없습니다.")
                    return

                # [개선] 권한 에러 방지를 위한 예외 처리 추가
                try:
                    # 기존 티어 역할 제거
                    roles_to_remove = [r for r in ctx.author.roles if r.name in TIER_LIST]
                    if roles_to_remove:
                        await ctx.author.remove_roles(*roles_to_remove)
                    
                    # 새 역할 부여
                    await ctx.author.add_roles(new_role)
                    await ctx.send(f"🔄 **{user_tier}** 역할 부여 완료!")
                except discord.Forbidden:
                    await ctx.send("❌ 봇의 권한이 부족합니다. 서버 설정에서 **봇의 역할 순위를 티어 역할보다 위로** 올려주세요!")

        except Exception:
            await ctx.send("갱신 중 오류가 발생했습니다.")

bot.run(DISCORD_TOKEN)

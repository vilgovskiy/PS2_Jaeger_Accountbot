from discord.ext import commands
import discord
from .utils.shared_recources import dbPool
import gspread
import datetime
import random
import logging
from asyncpg import PostgresError

class Account:
    def __init__(self, name:str, password: str, last_user: str, last_booked: datetime.datetime):
        self.name = name
        self.password = password
        self.last_user = last_user
        self.last_booked = last_booked

    def embed(self):
        terms_of_service = "\u2022 You may only use the account for this occation.\n\u2022 You are not allowed create, delete, or add characters to the account.\n\u2022 You are not allowed to ASP the charakter.\n" \
                           "\u2022 You are expected to follow the [Jaeger Code of Conduct](https://docs.google.com/document/d/1zlx6BgZKHyKvt2d04d1jnyjvNZLgeLgsPANg38ANRS4/edit) and not disturb any of the [currently ongoing events](https://docs.google.com/spreadsheets/d/1eA4ybkAiz-nv_mPxu_laL504nwTDmc-9GnsojnTiSRE/edit) on the server.\n" \
                           "\u2022 Failure to follow these rules may result in repercussions, both for you personally and for your outfit."

        embed = discord.Embed(title="Account Assignment")
        embed.add_field(name="Account", value=self.name, inline=True)
        embed.add_field(name="Password", value=self.password, inline=True)
        embed.add_field(name="Terms of Service", value=terms_of_service, inline=False)

        return embed

    def is_booked(self):
        now = datetime.datetime.now(self.last_booked.tzinfo)

        formatstring = "%m/%d/%Y"
        now = now.strftime(formatstring)
        last_booked = self.last_booked.strftime(formatstring)

        if now == last_booked:
            return True
        else:
            return False

class AccountDistrubutor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.serviceAccount = gspread.service_account(filename=r"D:\Dateien\Programmieren\Python\PS2 Jaeger Accountbot\data\ps2jaegeraccountbot-8fd42185680c.json")

# TODO
# Outline:
# !account - gets currently assigned account if there is any
# !account get - gets an account if user doesnt have one yet
# !account distrubute - distribute accounts to mentions if accounts are free, skip those mentioned that already have one for the day
# !account forcedistribute - distributes accounts to mentions regardless of prior allocation

    def _get_sheet_data(self, url: str):
        """Fetches all relevant data from the spreadsheet"""
        sheet1 = shared_recources.gspread_service_account.open_by_url(url).sheet1
        sheet_data = sheet1.get("1:13")
        return sheet_data

    async def _get_accounts(self, ctx: commands.Context, sheet_data: list):
        """Parses accounts out of the raw data"""
        async with dbPool.acquire() as conn:
                async with conn.transaction():
                    utcoffset = await conn.fetchval("SELECT utcoffset FROM guilds WHERE guild_id = $1;", ctx.guild.id)

        accounts = []

        for row in sheet_data[1:]:
            name, password = row[0:2]

            indexed_row = enumerate(row)
            last_user = None
            for index, entry in reversed(list(indexed_row)):
                if entry != "":
                    last_user = entry
                    last_booked_str = sheet_data[:1][0][index]
                    try:
                        last_booked = datetime.datetime.strptime(last_booked_str, "%m/%d/%Y")
                        last_booked = last_booked.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=utcoffset))) # Makes datetime object timezone aware
                        break
                    except ValueError:
                        await ctx.send("```Error: There seems to be a date formatting error in the google sheets document.```")
                        raise NotImplementedError("TODO: Make custom errorhandler-compatible exception for invalid google-sheet values") #TODO: Make custom errorhandler-compatible exception for invalid google-sheet values to outsource this
                    
            accounts.append(Account(name, password, last_user, last_booked))        
        return accounts

    async def _user_has_account(self, ctx, accounts):
        for account in accounts:
            # Necessary because author.nick is None if the user has not changed his name on the server
            if not ctx.author.nick is None:
                name = ctx.author.nick
            else:
                name = ctx.author.name
            
            if account.last_user == name:
                if account.is_booked():
                    return account
        return None

##### Command Section #####
    @commands.guild_only()
    @commands.group(invoke_without_command=True)
    async def account(self, ctx):
        async with dbPool.acquire() as conn:
                async with conn.transaction():
                    url = await conn.fetchval("SELECT url FROM sheet_urls WHERE fk = (SELECT id FROM guilds WHERE guild_id = $1);", ctx.guild.id)
        if url is None:
            await ctx.send(f"{ctx.author.mention}\nThere is no google sheets url associated with this guild.\n"\
                            "Please use the `!jaeger_url` command to to set a url.")
            return
        sheet_data = await self.bot.loop.run_in_executor(None, self._get_sheet_data, url)
        accounts = await self._get_accounts(ctx, sheet_data)

        account = await self._user_has_account(ctx, accounts)
        if not account is None:
            await ctx.send(f"Your currently assigned account is: `{account.name}`.\n"\
                            "Please check your PMs for the login details.")
        else:
            await ctx.send(f"{ctx.author.mention}\nYou have not been assigned any accounts for today.\n"\
                            "Please use the `!account book` command or ask your OVO rep for account assignment.")

    @commands.guild_only()
    @account.command()
    async def book(self, ctx):
        async with dbPool.acquire() as conn:
                async with conn.transaction():
                    url = await conn.fetchval("SELECT url FROM sheet_urls WHERE fk = (SELECT id FROM guilds WHERE guild_id = $1);", ctx.guild.id)
        if url is None:
            await ctx.send(f"{ctx.author.mention}\nThere is no google sheets url associated with this guild.\n"\
                            "Please use the `!jaeger_url` command to to set a url.")
            return
        
        sheet_data = await self.bot.loop.run_in_executor(None, self._get_sheet_data, url)
        accounts = await self._get_accounts(ctx, sheet_data)

        # Try to assign accounts to the person that last had it as often as possible
        for account in accounts:
            # Necessary because author.nick is None if the user has not changed his name on the server
            if not ctx.author.nick is None:
                name = ctx.author.nick
            else:
                name = ctx.author.name
            
            if account.last_user == name:
                if account.is_booked():
                    await ctx.send(f"You have already been assigned: `{account.name}`.\n"\
                                    "Please check your PMs for the login details.")
                    return
                else:
                    await ctx.author.send(embed=account.embed())
                    return
        #TODO actually enter this into the google sheet
        # If the user does not have any prior accounts, assign the first free one
        for account in accounts:
            if account.is_booked():
                continue
            else:
                await ctx.author.send(embed=account.embed())
                return
        
        # If the function made it this far, there are no free accounts available
        await ctx.author.send("````There are currently no free accounts.\nIf you really need one, talk to your OVO rep.```")

    @commands.guild_only()
    @commands.command()
    async def distribute_accounts(self, ctx: commands.Context):
        """
        Distributes accounts to all mentioned users.
        
        Arguments:
        force       Distributes accounts regardless of prior allocation
        """
        async with dbPool.acquire() as conn:
            async with conn.transaction():
                url = await conn.fetch('SELECT url FROM jaeger_urls WHERE fk = (SELECT id FROM guilds WHERE guild_id = $1);', ctx.guild.id)

        accounts = await self._get_accounts(url)
        
        if len(accounts) >= len(ctx.message.mentions):
            for member in ctx.message.mentions:
                random.shuffle(accounts)
                account = accounts.pop()
                await member.send(str(account))
                await ctx.author.send(f"Member {member.nick} has been assigned account {account.name}.")

        else:
            raise NotImplementedError("MAKE OWN EXCEPTION HERE")
            
def setup(bot):
    bot.add_cog(AccountDistrubutor(bot))


















"""
from __future__ import print_function
import gspread
from discord.ext import commands
import datetime

class Account:
    def __init__(self, accountName, accountPassword):
        self.name = accountName
        self.password = accountPassword
        self.available = True
    
    def setAvailability(self, val: bool):
        self.available = val

class AccountDistrubutor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.serviceAccount = gspread.service_account(filename=r"D:\Dateien\Programmieren\Python\PS2 Jaeger Accountbot\data\ps2jaegeraccountbot-8fd42185680c.json")

    async def _getAccounts(self):
        "
        def _getWorksheet(url):
            
            try:
                worksheet = serviceAccount.open_by_url(string(url)).sheet1 # get the first worksheet of the spreadsheet returned by open_by_url
                return worksheet
            except Exception as e:
                print(e) #TODO make bot exception to be caught by errorhandler
                return None

        worksheet = None
        async with dbPool.acquire() as conn:
            async with conn.transaction():
                sheetsAddress = conn.fetchval("SELECT sheets_url FROM sheets_urls WHERE fk = (SELECT id FROM guilds WHERE guild_id = $1);", ctx.guild.id)
                if not sheetsAddress is None:
                    worksheet = self.bot.loop.run_in_executor(None, _getWorksheet, sheetsAddress)
                else:
                    #TODO make bot exception to be caught by errorhandler
                    raise Exception("SheetsAddress is none, NOT IMPLEMENTED")
            
        # Get everything in columns A & B
        columnA = self.bot.loop.run_in_executor(None, worksheet.col_values, 1)
        columnB = self.bot.loop.run_in_executor(None, worksheet.col_values, 2)

        # Remove Header from list (e.g. Account Name)
        if columnA[0] != "Account Name" or columnB[0] != "Password":
            #TODO make bot exception to be caught by errorhandler
            raise Exception("Something is terribly wrong, contact administrator and check spreadsheet for integrity")
        del columnA[0]
        del columnB[0]
        
        # Create a list of availablable Account objects, and filter example accounts
        accounts = []
        for accountName, password in columnA, columnB:
            if accountName == "" or password == "":
                break
            accounts.append(Account(accountName,password))

        datetime.datetime.now() # TODO get discord server's timezone and validate account availability



    def _isAvailable()

    def _getAccount()






    @commands.group()
    @commands.check(isOutfitRep())
    def accounts(self, ctx):
        sheetsAddress = None
        async with dbPool.acquire() as conn:
            async with conn.transaction():
                sheetsAddress = conn.fetchval("SELECT sheets_url FROM sheets_urls WHERE fk = (SELECT id FROM guilds WHERE guild_id = $1);", ctx.guild.id)
        if not sheetsAddress is None:
            try:
                worksheet = serviceAccount.open_by_url("https://docs.google.com/spreadsheets/d/1Kad_6iSXRfFeiJFX3Qub-e6QApgNeCCc5rhTFCAjPB4/edit#gid=0").sheet1 # get the first worksheet of the spreadsheet returned by open_by_url
            except Exception as e:
                print(e)
            

    @accounts.command()
    @commands.check(isOutfitRep())
    def distribute(self, ctx):
        pass

    @commands.command


serviceAccount = gspread.service_account(filename=r"D:\Dateien\Programmieren\Python\PS2 Jaeger Accountbot\data\ps2jaegeraccountbot-8fd42185680c.json")
worksheet = serviceAccount.open_by_url("https://docs.google.com/spreadsheets/d/1Kad_6iSXRfFeiJFX3Qub-e6QApgNeCCc5rhTFCAjPB4/edit#gid=0").sheet1 # get the first worksheet of the spreadsheet returned by open_by_url

# Get everything in columns A & B
columnA = worksheet.col_values(1)
columnB = worksheet.col_values(2)

# Remove Header (e.g. Account Name)
if columnA[0] != "Account Name" or columnB[0] != "Password":
    raise Exception("Something is terribly wrong, contact administrator and check spreadsheet for integrity")
del columnA[0]
del columnB[0]

# Create a list of availablable Account objects, and filter example accounts
accounts = []
for accountName, password in columnA, columnB:
    if accountName == "" or password == "":
        break
    accounts.append(Account(accountName,password))




# accountNames = 
# accountPasswords =

# print(vals)
"""
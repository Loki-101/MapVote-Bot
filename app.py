import asyncio
import logging
import os
import random
import secrets
import time
from collections import defaultdict
from contextlib import suppress
from functools import partial

import discord
from dotenv import load_dotenv

# Config

MAP_POOL_SIZE = 3
# Hours before a chosen map can be drawn again in the same server, 0 disables
NO_REPEAT_PERIOD = 24
# Discord interaction tokens expire after 15 minutes, keep this below 900
SESSION_TIMEOUT = 600 # Seconds

# Map pool

MAP_POOL = {
    "Assault": (
        "Hanamura[Original, Winter]",
        "Horizon Lunar Colony",
        "Paris",
        "Temple of Anubis",
        "Volskaya Industries",
    ),
    # "Clash": (
    #     "Hanaoka",
    #     "Throne of Anubis",
    # ),
    "Control": (
        "Antarctic Peninsula",
        "Busan",
        "Ilios[Evening, Morning, Night]",
        "Lijiang Tower[Morning, Dawn, Night]",
        "Nepal[Evening, Morning]",
        "Oasis[Evening, Morning, Night]",
        "Samoa",
    ),
    "Escort": (
        "Circuit Royal[Morning, Night]",
        "Dorado[Evening, Night]",
        "Havana[Morning, Night]",
        "Junkertown[Morning, Night]",
        "Rialto[Sunrise, Morning, Evening]",
        "Route 66[Morning, Overcast, Night]",
        "Shambali Monastery[Morning, Night]",
        "Watchpoint: Gibraltar[Morning, Evening]",
        "Watchpoint: Grímsvötn",
    ),
    # "Flashpoint": (
    #     "Aatlis",
    #     "New Junk City",
    #     "Suravasa",
    # ),
    "Hybrid": (
        "Blizzard World[Morning, Overcast, Night, Winter]",
        "Eichenwalde[Morning, Evening]",
        "Hollywood[Morning, Night, Sunset]",
        "King's Row[Overcast, Night, Evening, Winter]",
        "Midtown[Morning, Night]",
        "Neon Junction[Morning, Night]",
        "Numbani",
        "Paraíso",
    ),
    # "Push": (
    #     "Colosseo[Evening, Night, Morning]",
    #     "Esperança[Night, Morning]",
    #     "New Queen Street[Dawn, Morning]",
    #     "Runasapi",
    # ),
}


def parse_map(entry: str) -> tuple[str, tuple[str, ...]]:
    name, _, variants = entry.strip().removesuffix("]").partition("[")
    return name.strip(), tuple(v.strip() for v in variants.split(",") if v.strip())


MAPS = {category: dict(map(parse_map, entries)) for category, entries in MAP_POOL.items()}

CATEGORY_PICKS = len(MAPS) // 2 + 1

# Map history

recent_maps: defaultdict[tuple[int, str], dict[str, float]] = defaultdict(dict)


def available_maps(guild_id: int, category: str) -> list[str]:
    maps = list(MAPS[category])
    if not NO_REPEAT_PERIOD:
        return maps

    history = recent_maps[guild_id, category]
    cutoff = time.monotonic() - NO_REPEAT_PERIOD * 3600
    fresh = [m for m in maps if m not in history or history[m] < cutoff]
    if len(fresh) < min(len(maps), MAP_POOL_SIZE):
        history.clear()
        return maps
    return fresh


def remember_map(guild_id: int, category: str, map_name: str):
    if NO_REPEAT_PERIOD:
        recent_maps[guild_id, category][map_name] = time.monotonic()


def random_note(options: list[str]) -> str:
    return f"\n-# Selected at random from {', '.join(options)}." if len(options) > 1 else ""


# Vote session

class VoteSession(discord.ui.DesignerView):
    def __init__(self, guild_id: int, host: discord.Member, captains: tuple[discord.Member, discord.Member]):
        super().__init__(timeout=None)
        self.id = secrets.token_hex(4)
        self.guild_id = guild_id
        self.host = host
        self.captains = captains
        self.expires_at = int(time.time()) + SESSION_TIMEOUT
        self.picks: dict[int, list[str]] = {}
        self.category: str | None = None
        self.pool: list[str] = []
        self.bans: list[str] = []
        self.total_bans = 0
        self.final_map: str | None = None
        self.variant_votes: dict[int, str] = {}
        self.outcome: str | None = None
        self.render()

    @property
    def variants(self) -> tuple[str, ...]:
        return MAPS[self.category][self.final_map] if self.final_map else ()

    @property
    def banning_captain(self) -> discord.Member:
        return self.captains[len(self.bans) % len(self.captains)]

    def render(self):
        self.clear_items()
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## Map Vote\n{self.captains[0].mention} vs {self.captains[1].mention}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(self.status_text()),
        )
        if self.outcome is None:
            for row in self.controls():
                container.add_item(row)
            container.add_item(discord.ui.Separator())
            cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id=f"{self.id}:cancel")
            cancel.callback = self.cancel
            container.add_item(discord.ui.ActionRow(cancel))
            container.add_item(discord.ui.TextDisplay(f"-# Expires <t:{self.expires_at}:R>"))
        self.add_item(container)

    def status_text(self) -> str:
        if self.category is None:
            lines = [
                f"{c.mention} selected their categories." if c.id in self.picks
                else f"Waiting on {c.mention} to select {CATEGORY_PICKS} categories."
                for c in self.captains
            ]
        else:
            lines = [f"The map category will be ``{self.category}``!"]
            lines += [f"{self.captains[i % len(self.captains)].mention} banned the map ``{m}``." for i, m in enumerate(self.bans)]
            if self.final_map is None:
                if self.outcome is None:
                    lines.append(f"{self.banning_captain.mention}, please ban one map.")
            elif self.variants:
                lines.append(f"The map will be ``{self.final_map}``!{random_note(self.pool)}")
                if self.outcome is None:
                    lines += [
                        f"{c.mention} voted for a variant." if c.id in self.variant_votes
                        else f"Waiting on {c.mention} to vote for a variant."
                        for c in self.captains
                    ]
        if self.outcome:
            lines.append(self.outcome)
        return "\n".join(lines)

    def controls(self) -> list[discord.ui.ActionRow]:
        if self.category is None:
            select = discord.ui.Select(
                custom_id=f"{self.id}:categories",
                placeholder=f"Select {CATEGORY_PICKS} categories by order of preference",
                min_values=CATEGORY_PICKS,
                max_values=CATEGORY_PICKS,
                options=[discord.SelectOption(label=category) for category in MAPS],
            )
            select.callback = partial(self.pick_categories, select)
            return [discord.ui.ActionRow(select)]

        if self.final_map is not None:
            buttons = []
            for variant in self.variants:
                button = discord.ui.Button(label=variant, style=discord.ButtonStyle.primary, custom_id=f"{self.id}:variant:{variant}")
                button.callback = partial(self.vote_variant, variant)
                buttons.append(button)
            return [discord.ui.ActionRow(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]

        buttons = []
        for map_name in self.pool:
            button = discord.ui.Button(label=map_name, style=discord.ButtonStyle.success, custom_id=f"{self.id}:ban:{map_name}")
            button.callback = partial(self.ban, map_name)
            buttons.append(button)
        return [discord.ui.ActionRow(*buttons[i:i + 5]) for i in range(0, len(buttons), 5)]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.outcome is not None:
            await reject(interaction, "This map vote has already ended.")
            return False
        if interaction.user.id not in {self.host.id, *(c.id for c in self.captains)}:
            await reject(interaction, "You're not authorized to interact with this menu.")
            return False
        return True

    async def pick_categories(self, select: discord.ui.Select, interaction: discord.Interaction):
        if interaction.user.id not in {c.id for c in self.captains}:
            return await reject(interaction, "Only the team captains can select categories.")
        if interaction.user.id in self.picks:
            return await reject(interaction, "You've already selected your categories.")

        self.picks[interaction.user.id] = list(select.values)
        if len(self.picks) == len(self.captains):
            self.draw_pool()
        await self.update(interaction)

    async def ban(self, map_name: str, interaction: discord.Interaction):
        if interaction.user.id != self.banning_captain.id:
            return await reject(interaction, f"It's {self.banning_captain.mention}'s turn to ban.")
        if self.final_map is not None or map_name not in self.pool:
            return await reject(interaction, f"``{map_name}`` can't be banned anymore.")

        self.bans.append(map_name)
        self.pool.remove(map_name)
        if len(self.bans) == self.total_bans:
            self.pick_final()
        await self.update(interaction)

    async def vote_variant(self, variant: str, interaction: discord.Interaction):
        if interaction.user.id not in {c.id for c in self.captains}:
            return await reject(interaction, "Only the team captains can vote for a variant.")
        if interaction.user.id in self.variant_votes:
            return await reject(interaction, "You've already voted for a variant.")

        self.variant_votes[interaction.user.id] = variant
        if len(self.variant_votes) == len(self.captains):
            votes = list(self.variant_votes.values())
            remember_map(self.guild_id, self.category, self.final_map)
            self.finish(f"### The variant will be: ``{random.choice(votes)}``{random_note(list(dict.fromkeys(votes)))}")
        await self.update(interaction)

    def draw_pool(self):
        # Earlier picks are worth more: first = CATEGORY_PICKS points, last = 1
        overlap = set.intersection(*map(set, self.picks.values()))
        scores = {c: sum(CATEGORY_PICKS - picks.index(c) for picks in self.picks.values()) for c in overlap}
        best = max(scores.values())
        self.category = random.choice(sorted(c for c, s in scores.items() if s == best))
        maps = available_maps(self.guild_id, self.category)
        self.pool = random.sample(maps, min(len(maps), MAP_POOL_SIZE))
        self.total_bans = (len(self.pool) - 1) // len(self.captains) * len(self.captains)
        if self.total_bans == 0:
            self.pick_final()

    def pick_final(self):
        self.final_map = random.choice(self.pool)
        if not self.variants:
            remember_map(self.guild_id, self.category, self.final_map)
            self.finish(f"### The map will be: ``{self.final_map}``{random_note(self.pool)}")

    async def cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.host.id:
            return await reject(interaction, f"Only {self.host.mention} can cancel this map vote.")

        self.finish(f"Map vote cancelled by {self.host.mention}.")
        await self.update(interaction)

    async def end(self, outcome: str):
        if self.outcome is not None:
            return
        self.finish(outcome)
        self.render()
        if self.message:
            with suppress(discord.HTTPException):
                await self.message.edit(view=self)

    def finish(self, outcome: str):
        self.outcome = outcome
        self.stop()

    async def update(self, interaction: discord.Interaction):
        self.render()
        await interaction.response.edit_message(view=self)


async def reject(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message, ephemeral=True)


# Bot

class MapVoteBot(discord.Bot):
    async def close(self):
        for session in list(sessions.values()):
            await session.end("Map vote stopped because the bot went offline.")
        await super().close()


bot = MapVoteBot()
sessions: dict[str, VoteSession] = {}


@bot.slash_command(
    description="Starts a map vote between two team captains.",
    contexts={discord.InteractionContextType.guild},
)
@discord.option("captain1", description="Team Captain 1")
@discord.option("captain2", description="Team Captain 2")
async def mapvote(ctx: discord.ApplicationContext, captain1: discord.Member, captain2: discord.Member):
    captains = (captain1, captain2)
    if captain1 == captain2:
        return await ctx.respond("The two team captains must be different people.", ephemeral=True)
    if any(captain.bot for captain in captains):
        return await ctx.respond("Bots can't be team captains.", ephemeral=True)
    if any(captain in session.captains for session in sessions.values() for captain in captains):
        return await ctx.respond("One of those team captains is already in a map vote.", ephemeral=True)

    session = VoteSession(ctx.guild_id, ctx.author, captains)
    sessions[session.id] = session
    try:
        await ctx.respond(view=session)
        await asyncio.wait_for(session.wait(), SESSION_TIMEOUT)
    except TimeoutError:
        await session.end("Map vote timed out.")
    finally:
        sessions.pop(session.id, None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set in the environment or a .env file.")
    bot.run(token)
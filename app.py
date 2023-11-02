import discord
import random
import logging
import functools

# Set up logging
logging.basicConfig(level=logging.INFO)

# Create a Discord bot instance
bot = discord.Bot()

# Flag to track if a map vote is in progress
in_progress = False

# Define map sets for different game modes
map_sets = {
    "Control": ["Busan", "Ilios", "Lijang Tower", "Nepal", "Oasis", "Antarctic Peninsula", "Samoa"],
    "Escort": ["Circuit Royal", "Dorado", "Havana", "Junkertown", "Rialto", "Route 66", "Shambali Monastery", "Watchpoint Gibraltar"],
    "Flashpoint": ["New Junk City", "Suravasa"],
    "Hybrid": ["Blizzard World", "Eichenwalde", "Hollywood", "King's Row", "Midtown", "Numbani", "Paraiso"],
    "Assault": ["Hanamura", "Horizon Lunar Colony", "Paris", "Temple of Anubis", "Volskaya Industries"],
    "Push": ["Colosseo", "Esperanca", "New Queen Street"]
}

# Custom class to handle category selection
class CategorySelect(discord.ui.View):
    def __init__(self, user_id, ctx):
        super().__init__()
        self.user_id = user_id
        self.ctx = ctx
        self.selected_categories = []

    # Dropdown menu for category selection
    @discord.ui.select(
        placeholder="Select exactly 4 categories",
        min_values=4,
        max_values=4,
        options=[
            discord.SelectOption(label="Control"),
            discord.SelectOption(label="Escort"),
            discord.SelectOption(label="Flashpoint"),
            discord.SelectOption(label="Hybrid"),
            discord.SelectOption(label="Assault"),
            discord.SelectOption(label="Push")
        ]
    )
    async def select_callback(self, select, interaction):
        try:
            # Check user authorization
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("You're not authorized to interact with this menu.", ephemeral=True)
                return

            # Store selected categories
            self.selected_categories = select.values

            # Provide feedback and stop the view
            await interaction.message.delete()
            await self.ctx.send(f"User {interaction.user.mention} selected {', '.join(self.selected_categories)}.")
            self.stop()
        except Exception as e:
            logging.debug(f"Exception in CategorySelect: {e}")

# Custom class to handle map selection
class MapSelect(discord.ui.View):
    def __init__(self, user_id, ctx, maps):
        super().__init__()
        self.user_id = user_id
        self.ctx = ctx
        self.maps = maps
        self.selected_map = None

        # Create buttons for each map
        for map_name in self.maps:
            button = discord.ui.Button(label=map_name, style=discord.ButtonStyle.green, custom_id=map_name)
            button.callback = functools.partial(self.button_callback, button)
            self.add_item(button)

    # Callback for map selection button
    async def button_callback(self, button: discord.ui.Button, interaction: discord.Interaction):
        try:
            # Check user authorization
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("You're not authorized to interact with this menu.", ephemeral=True)
                return

            # Update button appearance and disable it
            self.selected_map = button.label
            button.style = discord.ButtonStyle.danger
            button.disabled = True

            # Edit the message to show the selected map and stop the view
            await interaction.response.edit_message(
                content=f"{interaction.user.mention} banned the map {self.selected_map}.",
                view=self
            )
            self.stop()
        except Exception as e:
            logging.debug(f"Exception in MapSelect: {e}")

    # Set the available maps dynamically
    def set_maps(self, maps):
        logging.info(f"Setting maps: {maps}")
        self.select.options = [discord.SelectOption(label=map_name) for map_name in maps]
        logging.info(f"Set select.options: {self.select.options}")

# Function to conduct a map vote
async def map_vote(ctx, captain1: discord.User, captain2: discord.User):
    try:
        global in_progress
        logging.info(f"Initial in_progress: {in_progress}")

        # Check if a map vote is already in progress
        if in_progress:
            logging.warning("Map vote already in progress.")
            await ctx.send("A map vote is already in progress.")
            return

        # Start a new map vote
        logging.info("Starting map vote...")
        in_progress = True

        # Create dropdown for Team Captain 1
        view1 = CategorySelect(captain1.id, ctx)
        await ctx.respond(f"{captain1.mention}, please select 4 categories.", view=view1)
        await view1.wait()

        # Team Captain 1's selection
        categories1 = view1.selected_categories
        logging.info(f"Categories1: {categories1}")

        # Create dropdown for Team Captain 2
        view2 = CategorySelect(captain2.id, ctx)
        await ctx.send(f"{captain2.mention}, please select 4 categories.", view=view2)
        await view2.wait()

        # Team Captain 2's selection
        categories2 = view2.selected_categories
        logging.info(f"Categories2: {categories2}")

        # Find overlapping category
        overlapping_categories = list(set(categories1) & set(categories2))
        logging.info(f"Overlapping categories: {overlapping_categories}")
        selected_category = random.choice(overlapping_categories)
        logging.info(f"Selected category: {selected_category}")
        await ctx.send(f"The map category will be ``{selected_category}``!")

        # Determine number of maps in the selected category
        num_maps = len(map_sets[selected_category])
        logging.info(f"Number of maps in selected category: {num_maps}")

        # Skip bans if only 1 or 2 maps are available
        if num_maps <= 2:
            in_progress = False  # Reset the flag here
            logging.info(f"Skipping bans, in_progress set to {in_progress}")
            if num_maps == 2:
                await ctx.send("Skipping map bans and selecting a map at random as there are only 2 maps.")
                final_map = random.choice(map_sets[selected_category])
            else:  # num_maps == 1
                await ctx.send("Skipping map bans as there is only 1 map.")
                final_map = map_sets[selected_category][0]
            await ctx.send(f"The map will be: {final_map}")
            return

        # Create buttons for Team Captain 1 to ban
        maps = random.sample(map_sets[selected_category], 3)
        logging.info(f"Sampled maps for banning: {maps}")
        view3 = MapSelect(captain1.id, ctx, maps)
        await ctx.send(f"{captain1.mention}, please ban one map.", view=view3)
        await view3.wait()

        # Team Captain 1's ban
        banned_map1 = view3.selected_map
        logging.info(f"Banned map1: {banned_map1}")
        maps.remove(banned_map1)

        # Create buttons for Team Captain 2 to ban
        view4 = MapSelect(captain2.id, ctx, maps)  # Changed this line
        await ctx.send(f"{captain2.mention}, please ban one map.", view=view4)
        await view4.wait()

        # Team Captain 2's ban
        banned_map2 = view4.selected_map
        logging.info(f"Banned map2: {banned_map2}")
        maps.remove(banned_map2)

        # Output the final result
        final_map = maps[0]
        logging.info(f"Final map: {final_map}")
        await ctx.send(f"The map will be: ``{final_map}``")
        logging.info("Map vote completed.")
        in_progress = False
    except Exception as e:
        logging.error(f"Exception in map_vote: {e}")
        await ctx.send("An error occurred. Please try again.")
        in_progress = False

# Command to start a map vote
@bot.command(description="Starts a map vote between two team captains.")
async def mapvote(ctx,
    captain1: discord.Option(discord.SlashCommandOptionType.user, description="Team Captain 1"),
    captain2: discord.Option(discord.SlashCommandOptionType.user, description="Team Captain 2")):

    required_role_id = 458833002643062804
    member = ctx.guild.get_member(ctx.author.id)

    # Check if the user has the required role
    if required_role_id not in [role.id for role in member.roles]:
        required_role = ctx.guild.get_role(required_role_id)
        await ctx.respond(f"You need the {required_role.name} role to use this command.", ephemeral=True)
        return

    try:
        await map_vote(ctx, captain1, captain2)
    except Exception as e:
        logging.error(f"Exception in mapvote: {e}")
        await ctx.send("An error occurred. Please try again.")

# Run the bot - your Discord Bot's token goes here
bot.run("CHANGE_ME")

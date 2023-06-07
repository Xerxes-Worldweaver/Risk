from discord import Client, File, Intents
from display import draw_map
from maps import MAPS
import db_connector as db
import random as r
import itertools

intents = Intents.default()
intents.message_content = True
client = Client(intents=intents)


def generate_new_game_data(
    players: list[int],
    map: str = "classic",
    randomfill: bool = False
) -> dict:
    """Creates and returns a dictionary with game data."""
    game = {}
    map_data = MAPS[map]

    # Initializing players
    deployable_troops = 0 if randomfill else (40, 35, 30, 25, 20)[len(players)-2]
    r.shuffle(players)
    game["players"] = {
        str(player_id) : { # JSON doesn't allow integer keys; pain ensues
            "turn_number" : i+1,
            "colour" : ("red", "blue", "yellow", "green", "brown", "black")[i],
            "territories" : [],
            "cards" : [],
            "deployable_troops" : deployable_troops
        } for i, player_id in enumerate(players)
    }

    # Initializing territories
    game["map"] = map
    game["territories"] = {
        key : {"owner" : None, "troops" : 0}
        for key in map_data["connections"].keys()
    }
    if randomfill:
        for t_name, t_data in game["territories"].items():
            lucky_player = r.choice(players)
            t_data["owner"] = lucky_player
            t_data["troops"] = r.randint(1, 10)
            game["players"][str(lucky_player)]["territories"].append(t_name)
        player = game["players"][str(players[0])]
        player["deployable_troops"] = calculate_new_troops(game, str(players[0]))

    # Initializing deck and discard pile
    territory_names = [_ for _ in map_data["connections"].keys()]
    r.shuffle(territory_names)
    game["deck"] = [("Wild", None), ("Wild", None)] + [
        (("Infantry", "Cavalry", "Artillery")[i%3], territory_names[i])
        for i in range(len(territory_names))
    ]
    r.shuffle(game["deck"])
    game["discard_pile"] = []
            
    # Other game variables
    game["turn_order"] = players.copy()
    game["active_player"] = 1
    game["eliminated_players"] = []
    game["turn_stage"] = 1
    game["in_pregame"] = False if randomfill else True
    game["unclaimed_territories"] = 0 if randomfill else len(territory_names)
    game["last_attack"] = None
    game["card_claimed"] = False
    game["trade_count"] = 0
    game["active"] = True

    return game


def calculate_new_troops(game: dict, player_id: int) -> int:
    """Calculates the number of new troops a player would receive."""
    player_territories = game["players"][str(player_id)]["territories"]

    #The number of territories you occupy.
    new_troops = len(player_territories) // 3
    if new_troops < 3: new_troops = 3

    #The value of the continents you control.
    for continent in MAPS[game["map"]]["continents"]:
        if continent["territories"].issubset(player_territories):
            new_troops += continent["bonus"]
        
    return new_troops


def begin_next_player_turn(game: dict) -> str:
    """Ends current turn, starts next turn. Returns the id of the player whose turn it is."""
    # Start by cycling active_player status to the next player
    while True:
        game["active_player"] += 1
        if game["active_player"] > len(game["players"]):
            game["active_player"] = 1
        if game["active_player"] in game["eliminated_players"]:
            continue
        break

    player_id = game["turn_order"][game["active_player"]-1]
    player = game["players"][str(player_id)]

    # Handle pregame scenarios
    if game["in_pregame"]:
        if player["deployable_troops"] == 0:
            game["in_pregame"] = False
        else:
            return player_id
    
    player["deployable_troops"] = calculate_new_troops(game, player_id)
    game["turn_stage"] = 1 if len(player["cards"]) < 5 else 0
    game["last_attack"] = None
    game["card_claimed"] = False

    return player_id


def generate_turn_start_message(game: dict) -> str:
    """Generates a message for the player whose turn it just became."""
    player_id = game["turn_order"][game["active_player"]-1]
    troops = game["players"][str(player_id)]["deployable_troops"]
    s = "s" if troops > 1 else ""

    if game["in_pregame"]:
        message = f"It's your turn to deploy, <@{player_id}>. You have {troops} troop{s} remaining."
    else:
        message = f"It's your turn, <@{player_id}>; you have {troops} new troop{s} ready to be deployed."
        if game["turn_stage"] == 0:
            message += " But you have too many cards and must trade in a set before proceeding with your turn." 
    
    return message


# Configuring the bot commands
@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    # Ignore the bot's own messages
    if message.author == client.user:
        return
    # Rigged!
    if "rigged" in message.content.lower():
        await message.channel.send(f"#{db.increment_rigged_counter()}")
    # Ignore messages without the prefix
    if message.content[0] != "!":
        return

    author_id = message.author.id
    guild_id = message.guild.id
    args = message.content.split()
    command = args[0][1:]

    # Admin stuff
    if command == "admin" and author_id == 576592271361966080:
        if args[1] == "exec":
            await message.channel.send("Executing...")
            exec(" ".join([arg for arg in args[2:]]).replace('\\n', '\n'))
            return
        elif args[1] == "hack":
            author_id = int(args[2][2:-1])
            del args[2]
            del args[1]
            del args[0]
            command = args[0]


    # Starts a new game including the message sender and all mentioned players.
    if command == "play":
        
        # Check you're not already in a game
        if db.get_user_game_id(author_id, guild_id):
            await message.channel.send("You're already in a game on this server.")
            return

        # Finding the users mentioned in the message in order to add them to the game
        players = message.mentions.copy()
        for mention in players:
            if message.author == mention:
                players.remove(mention)
        if len(players) == 0:
            await message.channel.send("Unfortunately you cannot play by yourself.")
            return
        if len(players) > 5:
            await message.channel.send("Too many players; the maximum is 6.")
            return
        # Turning the player list into a player id list
        players = [player.id for player in players]

        # Checking to make sure none of the players are already in a game
        busy_players = []
        for player in players:
            if db.get_user_game_id(player, guild_id) != None:
                busy_players.append(f"<@{player}>")
        if busy_players:
            # Formatting the message
            n = len(busy_players)
            are = "are"
            if n == 1:
                busy_players = busy_players[0]
                are = "is"
            elif n == 2:
                busy_players = busy_players[0] + " and " + busy_players[1]
            else:
                busy_players = ", ".join(busy_players[0:-1]) + ", and " + busy_players[-1]
            await message.channel.send(f"{busy_players} {are} already in a game.")
            return

        # Creating a game in the inactive state
        game_map = args[1].lower if args[1].lower in list(MAPS.keys()) else "classic"
        game_id = db.create_game({
            "players" : [str(player) for player in players] + [str(author_id)],
            "joined" : [False] * len(players) + [True],
            "active" : False,
            "map" : game_map,
            "randomfill" : bool(args[-1] == "randomfill")
        })
        # Updating game creator's current game
        db.ensure_user_exists(author_id, guild_id)
        db.update_user_game_pointer(author_id, guild_id, game_id)

        # Announcing
        players = ", ".join([f"<@{player}>" for player in players])
        await message.channel.send(f"Invited {players} to a game on the {game_map.title()} map.")
        return


    # Lets a user to join a game; starts the game if all invited players join.
    if command == "join":

        # Check user isn't already in a game
        if db.get_user_game_id(author_id, guild_id) is not None:
            await message.channel.send("You're already in a game on this server.")
            return
        # Check for malformed arguments
        try:
            gamemaster_id = int(args[1][2:-1])
        except (IndexError, ValueError):
            await message.channel.send("I'm not sure whose game you're trying to join.")
            return
        # Check the game exists
        game = db.get_user_game_data(gamemaster_id, guild_id)
        if game is None:
            await message.channel.send("That game doesn't exist.")
            return
        # Check user was invited
        if str(author_id) not in game["players"]:
            await message.channel.send("You weren't invited.")
            return
        # Check that the game is still waiting on invites
        if game["active"] == True:
            await message.channel.send("You can't rejoin games.")
            return

        # Updating user's game pointer
        game_id = db.get_user_game_id(gamemaster_id, guild_id)
        db.ensure_user_exists(author_id, guild_id)
        db.update_user_game_pointer(author_id, guild_id, game_id)

        # Updating local game variable, not updating database just yet
        game["joined"][game["players"].index(str(author_id))] = True

        # If some players still need to join, update database and return
        if False in game["joined"]:
            db.update_game(game_id, game)
            await message.channel.send(f"Joined {args[1]}'s game.")
            return
        
        # Otherwise, start the game!
        game = generate_new_game_data(game["players"], game["map"], game["randomfill"])
        db.update_game(game_id, game)
        announcement = f"New game created with id {game_id}.\n"
        for i, player in enumerate(game["players"], 1):
            colour = ("red", "blue", "yellow", "green", "brown", "black")[i-1]
            announcement += f"Player {i} ({colour}): <@{player}>\n"
        starting_player = [player for player in game["players"].keys()][0]
        await message.channel.send(
            announcement + "\n" + generate_turn_start_message(game),
            file=File(draw_map(game), "map.jpg")
        )
        return


    # Declines an invitation.
    if command == "decline":

        # Check for malformed arguments
        try:
            gamemaster_id = int(args[1][2:-1])
        except (IndexError, ValueError):
            await message.channel.send("I'm not sure whose invitation you're trying to decline.")
            return
        # Check the game exists
        game = db.get_user_game_data(gamemaster_id, guild_id)
        if game is None:
            await message.channel.send("That game doesn't exist.")
            return
        # Check user was invited
        if str(author_id) not in game["players"]:
            await message.channel.send("You weren't invited.")
            return

        # Resetting joined players' game pointers and deleting the game
        game_id = db.get_user_game_id(author_id, guild_id)
        players = game["players"]
        for i, player in enumerate(players):
            if game["joined"][i]:
                db.update_user_game_pointer(player, guild_id, None)
        db.delete_game(game_id)
        
        # Announcing deletion
        players = [f"<@{player}>" for player in players]
        await message.channel.send(f"{', '.join(players)}\n\n<@{author_id}> has declined the invitation; the game hosted by {players[-1]} has been cancelled.")
        return


    # Leaves and deletes a game that's still waiting for invites to be answered.
    if command == "leave":

        # Check user is in a game
        game = db.get_user_game_data(author_id, guild_id)
        if game is None:
            await message.channel.send("You're not in a game on this server.")
            return
        # Check that game hasn't started
        if game["active"] == True:
            await message.channel.send("Your game has started; use !resign instead.")
            return
        
        # Resetting joined players' game pointers and deleting the game
        game_id = db.get_user_game_id(author_id, guild_id)
        players = game["players"]
        for i, player in enumerate(players):
            if game["joined"][i]:
                db.update_user_game_pointer(player, guild_id, None)
        db.delete_game(game_id)
        
        # Announcing deletion
        players = [f"<@{player}>" for player in players]
        await message.channel.send(f"{', '.join(players)}\n\n<@{author_id}> has left the game; the game hosted by {players[-1]} has been cancelled.")
        return


    # Places troops upon your territories.
    if command == "deploy":
        
        # Check user is in game
        game = db.get_user_game_data(author_id, guild_id)
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        # Check it's the user's turn
        if game["active_player"] != game["players"][str(author_id)]["turn_number"]:
            await message.channel.send(f"It's not your turn, <@{author_id}>.")
            return
        # Check if user needs to trade in cards
        if game["turn_stage"] == 0:
            await message.channel.send(f"You must trade in a set of cards, <@{author_id}>. Type !trade to do so.")
            return
        # Check if all deployment has already been done
        if game["turn_stage"] == 2:
            await message.channel.send(f"You have no troops left to deploy, <@{author_id}>.")
            return
        # Check for correct number of arguments
        try:
            # Check for shorthand deploy syntax
            try:
                deployed_troops = int(args[1])
                deploy_location = " ".join(args[2:]).title()
            except ValueError:
                deployed_troops = 1
                deploy_location = " ".join(args[1:]).title()
        except IndexError:
            await message.channel.send("You didn't tell me where to deploy.")
            return
        # Check user isn't deploying multiple troops in the pregame
        if game["in_pregame"] and deployed_troops > 1:
            await message.channel.send("You can't deploy more than one troop at a time until the game setup is over.")
            return
        # Check user has that many troops
        if game["players"][str(author_id)]["deployable_troops"] < deployed_troops:
            await message.channel.send("You don't have that many troops.")
            return
        # Zero troops? Heh?
        if deployed_troops == 0:
            await message.channel.send("You tried your hardest, and by a great force of will, you successfully deployed zero troops! So great was your power that you successfully deployed zero troops to not just one location, but every location! Wow! You're so going to win this war. And it's still your turn, by the way. As though you needed any more power.")
            return
        # Negative troops? Wut?
        if deployed_troops < 0:
            await message.channel.send("SIKE joke's on you I patched that exploit")
            return
        # Check user referenced a real territory
        try:
            territory = game["territories"][deploy_location]
        except KeyError as key:
            await message.channel.send(f"Couldn't find the territory '{key}'.")
            return
        # Get off my property
        if territory["owner"] not in ("None", str(author_id)):
            await message.channel.send("Someone else owns that territory.")
            return
        # Must claim territories while there are territories to be claimed
        if game["unclaimed_territories"] and territory["owner"]:
            await message.channel.send("You must deploy on unclaimed territories while there are territories to be claimed.")
            return

        # Deploying troops
        game["players"][str(author_id)]["deployable_troops"] -= deployed_troops
        territory["troops"] += deployed_troops
        if territory["owner"] == None:
            territory["owner"] = str(author_id)
            game["unclaimed_territories"] -= 1
            game["players"][str(author_id)]["territories"].append(deploy_location)

        # Resolving post-deployment game logic; making the appropriate announcements
        announcement = f"Deployed {deployed_troops} troop{'s' if deployed_troops > 1 else ''} to {deploy_location}."
        file = None
        # End turn if deploying in pregame
        if game["in_pregame"]:
            begin_next_player_turn(game)
            announcement += "\n\n" + generate_turn_start_message(game)
            file = File(draw_map(game), "map.jpg")
        # If not in pregame and all troops deployed, enable attacking
        elif game["players"][str(author_id)]["deployable_troops"] == 0:
            game["turn_stage"] = 2
            announcement += "\n\nAll troops deployed. Attack as you please, general."
            file = File(draw_map(game), "map.jpg")
        db.update_user_game_data(author_id, guild_id, game)
        await message.channel.send(announcement, file=file)
        return


    # Triggers an attack.
    if command == "attack":

        game = db.get_user_game_data(author_id, guild_id)
        # Check user is in game
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        player = game["players"][str(author_id)]
        # Check it's user's turn
        if game["active_player"] != player["turn_number"]:
            await message.channel.send(f"It's not your turn, <@{author_id}>.")
            return
        # Check user is in the attacking stage
        if game["turn_stage"] != 2:
            await message.channel.send(f"You must first deploy all of your troops, <@{author_id}>. You still have {player['deployable_troops']} left.")
            return
        
        # Parsing
        try:
            args[1]
            string = []
            # Assigning the target and attacker variables
            for arg in args[1:]:
                if arg == "from":
                    target = " ".join(string).title()
                    if not target: raise NameError
                    string = []
                elif arg == "with":
                    target
                    attacker = " ".join(string).title()
                    if not attacker: raise NameError
                    string = []
                else:
                    string.append(arg)
            try:
                # If this doesn't trip a NameError then a "with" was parsed
                attacker
                army_size = int(string[0])
            except NameError:
                attacker = " ".join(string).title()
            except IndexError:
                raise ValueError
            target
        # Plenty of NameError baiting in the above code
        except (NameError, ValueError):
            await message.channel.send("Invalid syntax. Usage: !attack (target country) from (attacking country) [with (army size)]\n(e.g. !attack Siam from Indonesia with 2)")
            return
        # Might be using the shortcut
        except IndexError:
            if game["last_attack"]:
                target, attacker, army_size = game["last_attack"]
            else:
                await message.channel.send("Usage: !attack (target country) from (attacking country) [with (army size)]\n(e.g. !attack Siam from Indonesia with 2)\nAlternatively, !attack can be used on its own to repeat your previous attack. If you were attempting this, know that no previous attack was found.")
                return
        # Make sure army_size is assigned
        try: army_size
        except NameError: army_size = 3
        
        # Check the territories are real
        try:
            off_territory = game["territories"][attacker]
            def_territory = game["territories"][target]
        except KeyError as key:
            await message.channel.send(f"Couldn't find the territory '{key}'.")
            return
        # Check territories are adjacent
        if target not in MAPS[game["map"]]["connections"][attacker]:
            await message.channel.send("Those territories are not adjacent.")
            return
        # Check user owns the attacking territory
        if off_territory["owner"] != str(author_id):
            await message.channel.send("You can't attack from a territory you don't own.")
            return
        # Check user doesn't own the defending territory
        if def_territory["owner"] == str(author_id):
            await message.channel.send("You can't attack yourself.")
            return
        off_troops = off_territory["troops"]
        def_troops = def_territory["troops"]
        # Check attacking territory has enough troops to attack
        if off_troops == 1:
            await message.channel.send("You can't attack with one troop; doing so would leave your territory undefended.")
            return
        
        # Adjusting army size as necessary
        adjusted = False
        if army_size > 3:
            army_size = 3
            adjusted = True
        if off_troops <= army_size:
            army_size = off_troops - 1
            adjusted = True
        if adjusted:
            await message.channel.send(f"Automatically reducing attacking army size to {army_size}...")

        # Rolling the dice, counting the casualties
        off_dice = [r.randint(1, 6) for _ in range(army_size)]
        def_dice = [r.randint(1, 6) for _ in range(2 if def_territory["troops"] > 1 else 1)]
        off_dice.sort(reverse=True)
        def_dice.sort(reverse=True)
        off_dead, def_dead = 0, 0
        try:
            for i in range(2):
                if off_dice[i] > def_dice[i]: def_dead += 1
                else: off_dead += 1
        except IndexError: pass
        off_territory["troops"] -= off_dead
        def_territory["troops"] -= def_dead
        game["last_attack"] = (target, attacker, army_size)

        # Assembling results text
        those_who_lost = "both armies" if off_dead and def_dead else "attackers" if off_dead else "defenders"
        amount_text = "two troops" if 2 in (off_dead, def_dead) else "one troop"        
        changes = "("
        if those_who_lost != "defenders":
            changes += f"{off_troops} -> {off_troops - off_dead}"
            if those_who_lost == "both armies":
                changes += ", "
        if those_who_lost != "attackers":
            changes += f"{def_troops} -> {def_troops - def_dead}"
        changes += ")"
        results = f"Rolling...\n`Attackers ({off_troops}): {off_dice}`\n`Defenders ({def_troops}): {def_dice}`\n`Result: {those_who_lost} lose {amount_text}. {changes}`"

        # If territory was conquered...
        if def_territory["troops"] == 0:

            # Transfer ownership and troops
            conquered_player_id = def_territory["owner"]
            conquered_player = game["players"][str(conquered_player_id)]
            conquered_player["territories"].remove(target)
            player["territories"].append(target)
            def_territory["owner"] = str(author_id)
            def_territory["troops"] = army_size
            off_territory["troops"] -= army_size

            # Eliminate a player if he's out of turf
            if len(conquered_player["territories"]) == 0:
                game["discard_pile"] += conquered_player["cards"]
                conquered_player["cards"] = None
                game["eliminated_players"].append(conquered_player["turn_number"])
                results += f"\n\n<@{conquered_player_id}> has been eliminated."
                db.update_user_game_pointer(conquered_player_id, guild_id, None)

            # Check for victory and the game's end
            if len(player["territories"]) == len(MAPS[game["map"]]["connections"]):
                results += f"\n\nVICTORY! <@{author_id}> has conquered the world!"
                game_id = db.get_user_game_id(author_id, guild_id)
                db.update_user_game_pointer(author_id, guild_id, None)
                db.delete_game(game_id)
                await message.channel.send(results, file=File(draw_map(game), "map.jpg"))
                return

            # Announcing the territory ownership transfer and movement options
            results += f"\n\nYou've conquered {target}! {army_size} of your troops were automatically moved forward into that territory for you."
            max_troops = off_territory["troops"] - 1
            if max_troops == 1:
                results += f" But you can also type '!move' to move an additional 1 troop forward. (Doing some other move or attack will negate this opportunity.)"
            elif max_troops > 1:
                results += f" But you can also type '!move' to move {max_troops} additional troops forward (the maximum), or '!move (number)' to move a specific, lesser number of additional troops forward. (Doing some other move or attack will negate this opportunity.)"
            else:
                game["last_attack"] = None

            # Giving a card if no card has been claimed this turn
            if not game["card_claimed"]:
                # Shuffling if necessary
                if len(game["deck"]) == 0:
                    game["deck"] = [card for card in game["discard_pile"]]
                    r.shuffle(game["deck"])
                    game["discard_pile"] = []
                player["cards"].append(game["deck"].pop())
                game["card_claimed"] = True
                results += "\n\nFor conquering a territory this turn, you also gained a card."

        # If user's army was crippled...
        elif off_territory["troops"] == 1:
            game["last_attack"] = None
            results += f"\n\nYour army has grown too small to continue the attack."

        # Update database
        db.update_user_game_data(author_id, guild_id, game)

        # Add map image to the message if something happened
        file = None
        if def_territory["owner"] == str(author_id) or off_territory["troops"] == 1:
            file=File(draw_map(game), "map.jpg")
        await message.channel.send(results, file=file)
        return


    # Relocates troops after successful conquest or at the end of your turn.
    if command == "move":
        
        game = db.get_user_game_data(author_id, guild_id)
        # Check user is in a game
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        player = game["players"][str(author_id)]
        # Check it's the user's turn
        if game["active_player"] != player["turn_number"]:
            await message.channel.send(f"It's not your turn, <@{author_id}>.")
            return
        # Check user has deployed all troops
        if game["turn_stage"] != 2:
            await message.channel.send(f"You must first deploy all of your troops, <@{author_id}>. You still have {player['deployable_troops']} left.")
            return

        # Putting this long message here is better than wrapping the following block of code in one fat try statement and catching arbitrary SyntaxErrors
        move_command_syntax_error_message = "Invalid syntax. Usage: '!move (number of troops) from (starting territory) to (destination territory)'\n(e.g. '!move 5 from Egypt to Middle East')\nAfter conquering a territory, !move is also used to move more troops into the conquered territory, like so: '!move 5'."

        # Check if this is a move into a just-conquered territory
        try: args[2]
        except IndexError:
            # Check that there's a last_attack logged
            if not game["last_attack"]:
                try: args[1]
                except IndexError:
                    await message.channel.send(move_command_syntax_error_message[16:])
                    return
                await message.channel.send("I think you've forgotten something.")
                return
            # Check user has conquered the territory
            target, attacker, _ = game["last_attack"]
            target_territory = game["territories"][target]
            attacker_territory = game["territories"][attacker]
            if target_territory["owner"] != attacker_territory["owner"]:
                await message.channel.send("You haven't conquered the territory yet.")
                return
            # Check for troop count (set troop count to the max if it doesn't exist)
            try:
                troop_count = int(args[1])
                if attacker_territory["troops"] <= troop_count:
                    await message.channel.send("You're trying to move too many troops; one troop must always stay behind.")
                    return
            except IndexError:
                troop_count = attacker_territory["troops"] - 1
            except ValueError:
                await message.channel.send(move_command_syntax_error_message)
                return
            # Update troop numbers and clear last_attack (to disallow further movement)
            attacker_territory["troops"] -= troop_count
            target_territory["troops"] += troop_count
            game["last_attack"] = None
            # Update database and announce movement
            db.update_user_game_data(author_id, guild_id, game)
            await message.channel.send(f"Moved {troop_count} extra troop{'s' if troop_count > 1 else ''} to {target}, increasing its troop count to {target_territory['troops']}.")
            return
        
        # Parsing end-of-turn-movement syntax
        try:
            troop_count = int(args[1])
            if args[2] != "from": raise ValueError
        except ValueError:
            await message.channel.send(move_command_syntax_error_message)
            return
        try:
            string = []
            for arg in args[3:]:
                if arg == "to":
                    start = " ".join(string).title()
                    if not start: raise NameError
                    string = []
                else: string.append(arg)
            start
            destination = " ".join(string).title()
            if not destination: raise NameError
        except (NameError, IndexError):
            await message.channel.send(move_command_syntax_error_message)
            return

        # Check for legit territory names
        try:
            territory_a = game["territories"][start]
            territory_b = game["territories"][destination]
        except KeyError as key:
            await message.channel.send(f"Couldn't find the territory '{key}'.")
            return
        # Check that user owns both territories
        if territory_a["owner"] != str(author_id):
            await message.channel.send(f"You don't own {start}.")
            return
        if territory_b["owner"] != str(author_id):
            await message.channel.send(f"You don't own {destination}.")
            return
        # Check that the territories are different
        if start == destination:
            await message.channel.send("Just use !endturn lol.")
            return
        # Check that the numbers are legit
        if troop_count >= territory_a["troops"]:
            await message.channel.send("You're trying to move too many troops: at least one troop must always stay behind.")
            return
        if troop_count < 1:
            await message.channel.send("I suppose you thought that was terribly clever.")
            return
        
        # Check for a path between the territories
        connections = MAPS[game["map"]]["connections"]
        unexplored = [start]
        examined = []
        found_path = False
        while not found_path and len(unexplored):
            territory_name = unexplored.pop()
            for connection in connections[territory_name]:
                if connection in examined:
                    continue
                if game["territories"][connection]["owner"] == str(author_id):
                    if connection == destination:
                        found_path = True
                        break
                    else:
                        unexplored.append(connection)
                examined.append(connection)
        if not found_path:
            await message.channel.send("You don't own a path between those territories.")
            return
        
        # Transferring troops, starting the next player's turn, and updating database
        territory_a["troops"] -= troop_count
        territory_b["troops"] += troop_count
        begin_next_player_turn(game)
        db.update_user_game_data(author_id, guild_id, game)

        # Announcing transferal the beginning of a new turn
        start_message = generate_turn_start_message(game)
        destination_troops = territory_b["troops"]
        await message.channel.send(f"Moved {troop_count} extra troops to {destination}, increasing its troop count to {destination_troops}.")
        await message.channel.send(start_message, file=File(draw_map(game), "map.jpg"))
        return


    # Lets players see their cards.
    if command == "cards":

        # Check user is in game
        game = db.get_user_game_data(author_id, guild_id)
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return

        # Display the cards
        cards = game["players"][str(author_id)]["cards"]
        if not len(cards):
            await message.channel.send("You have no cards.")
            return
        display = "Your cards:"
        for card in cards:
            territory = card[1]
            if card[0] == "Infantry":
                display += f"\n> [:military_helmet: - {territory}]"
            elif card[0] == "Cavalry":
                display += f"\n> [:horse: - {territory}]"
            elif card[0] == "Artillery":
                display += f"\n> [:boom: - {territory}]"
            else:
                display += "\n> [:military_helmet: - :horse: - :boom: - Wild]"
        await message.channel.send(display)
        return


    # Trades in cards. Automatically selects cards if some are unspecified.
    if command == "trade":

        # Check user is in game
        game = db.get_user_game_data(author_id, guild_id)
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        # Check it's the user's turn
        if game["active_player"] != game["players"][str(author_id)]["turn_number"]:
            await message.channel.send(f"It's not your turn, <@{author_id}>.")
            return
        # Check deployment hasn't finished yet
        if game["turn_stage"] == 2:
            await message.channel.send(f"You've deployed all your troops and therefore can no longer trade, <@{author_id}>.")
            return
        player = game["players"][str(author_id)]
        cards = player["cards"]
        # Check player has enough cards
        if len(cards) < 3:
            await message.channel.send(f"You don't have enough cards to trade, <@{author_id}>.")
            return

        # Parsing
        selected_cards = []
        try:
            for i in range(1, 5): # We don't want args[0], that's the "!trade"
                card_index = int(args[i]) - 1 # This should throw an IndexError eventually
                if card_index < 0: raise ValueError
                try:
                    selected_cards.append(cards[card_index]) # Not this, though
                except IndexError as i:
                    if -1 < i < 21:
                        await message.channel.send(f"You don't have a {i}th card, mate.")
                    else:
                        await message.channel.send(f"Don't be absurd. No one has {i} cards.")
                    return
            # Too many arguments if no IndexError thrown
            raise ValueError
        except ValueError:
            await message.channel.send("Invalid syntax; use numbers (no commas) to indicate which cards (up to three) you're trading. (e.g. !trade 1 2 4)")
            return
        except IndexError:
            # All arguments recorded, moving on
            pass

        # Just a helpful inner function
        def check_set_legality(cards_to_be_checked):
            legal = False
            if len(cards_to_be_checked) == 3:
                L = [card[0] for card in cards_to_be_checked]
                L, wild = (L.count("Infantry"), L.count("Cavalry"), L.count("Artillery")), L.count("Wild")
                if wild or L.count(2) == 0: legal = True
            return legal

        # Legality checking and autoselecting
        if len(selected_cards) == 3:
            if not check_set_legality(selected_cards):
                await message.channel.send("That's not a legal set of cards.")
                return
        else: # Autoselecting
            # Filling a list named legal_sets with all possible legal sets of cards
            legal_sets = []
            unselected_cards = [card for card in cards if card not in selected_cards]
            for combination in itertools.combinations(unselected_cards, 3 - len(selected_cards)):
                possible_set = selected_cards + list(combination)
                if check_set_legality(possible_set):
                    legal_sets.append(possible_set)
            if not legal_sets:
                await message.channel.send(f"You don't have a complete set to trade in, {message.author.mention}.")
                return

        # If we haven't selected yet, that means we have multiple legal sets to choose from
        if len(selected_cards) != 3:
            # Calculating set scores
            scores = []
            for legal_set in legal_sets:
                score = 0
                card_types = []
                for card in legal_set:
                    if card[0] == "Wild": card_types.append("Wild")
                    elif card[1] in player["territories"]: card_types.append("Bonus")
                    else: card_types.append("Normal")
                # The criteria for the best set:
                # 1. Set has a bonus card.
                # 2. Set has a low number of wild cards.
                # 3. Set has a low number of bonus cards.
                if "Bonus" in card_types: score += 3
                wilds = card_types.count("Wild")
                if wilds:
                    if wilds == 1: score += 1
                else: score += 2
                if score == 5: score += card_types.count("Normal")
                scores.append(score)
            # Picking the set with the best score
            selected_cards = legal_sets[scores.index(max(scores))]

        # Discarding cards and figuring out if there's a bonus territory
        bonus_territory = None
        for card in selected_cards:
            if not bonus_territory and card[1] in player["territories"]:
                bonus_territory = card[1]
            cards.remove(card)
            game["discard_pile"].append(card)

        # Success! Have some troops
        try: new_troops = (4, 6, 8, 10, 12, 15)[game["trade_count"]]
        except IndexError: new_troops = ((game["trade_count"]-2)*5) #20, 25, 30...
        player["deployable_troops"] += new_troops
        if bonus_territory:
            game["territories"][bonus_territory]["troops"] += 2
        game["trade_count"] += 1
        
        # Allowing deployment if player was previously locked into a trade
        if game["turn_stage"] == 0:
            game["turn_stage"] = 1

        # Updating database and announcing the acquisition
        db.update_user_game_data(author_id, guild_id, game)
        await message.channel.send(f"You've received {new_troops} extra troops and now have {player['deployable_troops']} troops left to deploy." + (f" (Additionally, for trading in a card marked with {bonus_territory}, a territory you own, two extra troops were deployed to {bonus_territory}.)" if bonus_territory else ""))
        return


    # Displays the map.
    if command == "map":
        # Check user is in game
        game = db.get_user_game_data(author_id, guild_id)
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        # Send the map
        await message.channel.send(file=File(draw_map(game), "map.jpg"))
        return


    # Ends the player's turn.
    if command == "endturn":

        # Check user is in game
        game = db.get_user_game_data(author_id, guild_id)
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        player = game["players"][str(author_id)]
        # Check it's user's turn
        if game["active_player"] != player["turn_number"]:
            await message.channel.send(f"It's not your turn, <@{author_id}>.")
            return
        # Check user's already deployed all his units
        if game["turn_stage"] != 2:
            await message.channel.send(f"You must first deploy all of your troops, <@{author_id}>. You still have {player['deployable_troops']} left.")
            return

        # Start next turn and update database
        begin_next_player_turn(game)
        start_message = generate_turn_start_message(game)
        db.update_user_game_data(author_id, guild_id, game)
        await message.channel.send(start_message, file=File(draw_map(game), "map.jpg"))
        return


    # Leaves a game that's running.
    if command == "resign":

        # Check user is in game
        game = db.get_user_game_data(author_id, guild_id)
        if game == None:
            await message.channel.send(f"You're not in a game, <@{author_id}>.")
            return
        
        # Clean up data
        player = game["players"][str(author_id)]
        game["discard_pile"] += player["cards"]
        player["cards"] = None
        game["eliminated_players"].append(player["turn_number"])

        announcement = f"<@{author_id}> has resigned."

        # Determine if game is over
        game_over = False
        if len(game["players"]) == len(game["eliminated_players"]) + 1:
            winner_id = begin_next_player_turn(game)
            announcement += f"\n\nVICTORY! <@{winner_id}> has conquered the world! (Or most of it, anyway.)"
            db.update_user_game_pointer(winner_id, guild_id, None)
            game_over = True
        else:
            # If it was still the deployment stage of the game, give each player 5 troops
            if game["in_pregame"]:
                announcement += " Everyone has been given 5 additional troops to deploy as compensation."
                for nonquitter in game["players"].keys():
                    if nonquitter not in game["eliminated_players"]:
                        game["players"][str(nonquitter)]["deployable_troops"] += 5
            # If it was the resigning player's turn, cycle active_player
            if game["active_player"] == player["turn_number"]:
                begin_next_player_turn(game)
                announcement += "\n\n" + generate_turn_start_message(game)
        
        # Updating database and announcing the resignation and its consequences
        if game_over:
            db.delete_game(db.get_user_game_id(author_id, guild_id))
        else:
            db.update_user_game_data(author_id, guild_id, game)
        db.update_user_game_pointer(author_id, guild_id, None)
        await message.channel.send(announcement, file=File(draw_map(game), "map.jpg"))
        return


# Punch in the token and let it roll
with open("token.txt") as file: TOKEN = file.read()
client.run(TOKEN)

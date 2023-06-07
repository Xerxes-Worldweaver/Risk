from maps import MAPS
from PIL import Image, ImageDraw
from io import BytesIO

COLOUR_CODES = {
    "red"    : (200, 0, 0),
    "blue"   : (0, 0, 128),
    "yellow" : (255, 245, 0),
    "green"  : (0, 128, 0),
    "brown"  : (110, 38, 10),
    "black"  : (0, 0, 0),
    "grey"   : (128, 128, 128)
}

def draw_map(game: dict) -> BytesIO:
    """Function for returning a JPG representation of the current state of the game."""
    game_map = MAPS[game["map"]]
    territory_data = game["territories"]
    bubbles = game_map["bubbles"]

    # Readying appropriate map file
    with Image.open(game_map["file"]) as img:
        draw = ImageDraw.Draw(img)

        # Draw in each territory's bubble (troop amount and ownership indicator)
        for territory_name, bubble_pos in bubbles.items():
            # Determining the properties of the bubble
            owner  = territory_data[territory_name]["owner"]
            troops = territory_data[territory_name]["troops"]
            colour = COLOUR_CODES["grey" if owner == None else game["players"][str(owner)]["colour"]]
            bubble_box = (bubble_pos[0]-7, bubble_pos[1]-7, bubble_pos[0]+7, bubble_pos[1]+7)
            
            # Drawing in the coloured circle
            draw.ellipse(bubble_box, fill=colour)
            # and the number of troops
            draw.text((bubble_box[0] + 2 + (0 if troops > 9 else 3), bubble_box[1] + 2), str(troops), font=draw.getfont(), fill=((0, 0, 0) if colour == (255, 245, 0) else (255, 255, 255)))

        # Saving scribbled-on image to a byte array, and returning it
        byte_arr = BytesIO()
        img.save(byte_arr, format="JPEG")
        byte_arr.seek(0)
        return byte_arr
import requests
from mutagen.flac import FLAC, Picture
from re import findall, sub
import json
from os import listdir, rename, system
from sys import argv

from string import ascii_uppercase
from html import unescape
from progress.bar import IncrementalBar
from curses import tigetnum, setupterm


# Utilities

# makes text red or green
# param color: 0 for red, 1 for green
# return colored text
def colorize(text, color):
    if color != "":
        COLOR = {
            "GREEN": "\033[92m",
            "RED": "\033[91m",
            "ENDC": "\033[0m",
        }
        return (
            color * COLOR["GREEN"] + (1 - color) * COLOR["RED"] + text + COLOR["ENDC"]
        )
    else:
        return text


# checks if word is in name
# every word in the discogs track name must be in each file name
# case insensitive
# ignores single quotes
def matches(track, path):
    if track == path:
        return True

    if len(track) == len(path):
        return direct_match(track, path)
    else:
        return frameshift_match(track, path)


def direct_match(first, second, forgive=2):
    errors = 0
    first, second = list(first.lower()), list(second.lower())
    for i in range(len(first)):
        if first[i] != second[i]:
            errors += 1
        if errors > forgive:
            return False
    return True


def frameshift_match(first, second, forgive=2):
    first, second = list(first.lower()), list(second.lower())
    errors = 0
    not_matched = True
    i = 0
    while True:
        if i > len(second) - 1 or i > len(first) - 1:
            break

        if first[i] != second[i]:
            errors += 1
            longer = first if len(first) > len(second) else second
            longer.pop(i)
            i -= 1
        if errors > forgive:
            return False

        if first == second:
            return True

        i += 1
    longer = first if len(first) > len(second) else second
    shorter = first if len(first) < len(second) else second
    # if the longer one has excess that can be forgiven
    if (
        longer[: len(shorter)] == shorter
        and errors + (len(longer) - len(shorter)) <= forgive
    ):
        return True


def try_match(tags, path, pattern=None, ignore_paren=False):
    cols = tigetnum("cols")
    getFilename = lambda path: path.split("/")[-1]
    matched_tags, not_matched = match_tags(
        tags, path, pattern=pattern, ignore_paren=ignore_paren
    )
    not_found = 0
    album = matched_tags[0]["ALBUM"]
    artist = ""
    for g in matched_tags[0]["ARTIST"]:
        artist += g + ", " * (
            len(matched_tags[0]["ARTIST"]) > 1 and g != matched_tags[0]["ARTIST"][-1]
        )

    print(f"{artist} - {album}", end="\n\n")
    for track in matched_tags:
        try:
            name = colorize(track["TITLE"], 1) + " \u2192 "
            path = getFilename(track["path"])
            print(name, end="")
            print(path.rjust(cols // 2))
        except KeyError:
            name = colorize(track["TITLE"], 1) + " \u2192 "
            print(name, end="")
            print(colorize("Not found", 0))
            not_found += 1
            pass

    print(f"{not_matched} file(s) not matched.")


def set_track_tags(track):
    f = music_tag.load_file(track["path"])
    parent_dir = "/".join(track["path"].split("/")[:-1])

    f["album"] = track["album"]
    f["artist"] = track["artist"]
    f["tracktitle"] = track["name"]
    f["year"] = track["year"]

    # sets the artwork
    album = track["album"]
    art = requests.get(track["image"])
    img_path = f"{parent_dir}/cover.jpg"
    open(img_path, "wb").write(art.content)

    with open(img_path, "rb") as img_in:
        f["artwork"] = img_in.read()

    f.save()


"""
given pattern like '$artist - $track.m4a' and a filename 'the beatles - back in the ussr.m4a'
returns dict = {
    'artist': 'the beatles',
    'track': 'back in the ussr'
    ...
}
"""


def parse_filenames(pattern, name):
    is_var = False
    possible_vars = ["$artist", "$track", "$album", "$year", "$id", "$rand"]
    buffer = []
    vars = []
    for char in pattern:
        if char == "$":
            is_var = True
        if is_var:
            buffer.append(char)
        joined = "".join(buffer)
        if joined in possible_vars:
            vars.append(joined)
            is_var = False
            buffer = []

    # gets everything that isn't a var in the pattern
    remaining = get_surrounding(pattern, vars)
    # gets everything that isn't in the surroundings
    # end up with a list of the values
    final_values = get_surrounding(name, remaining)
    info = {}
    for i in range(len(vars)):
        info[vars[i][1:]] = final_values[i]

    return info


# returns list of surroundings of a string given vars
"""
example:
vars = ['foo', 'bar']
s = 'this isfooand    bar and some other things'
returns ['this is', 'and   ', ' and some other things']
"""


def get_surrounding(s, vars):
    surr = s.split(vars[0])
    for item in surr:
        for var in vars:
            if var in item:
                surr.extend(item.split(var))

    if "" in surr:
        surr.remove("")
    return surr


# formats the file name for searching
def format(track):
    track = track.replace(".m4a", "")
    track = track.replace(".flac", "")
    track = track.replace(" - ", " ")
    track = track.replace("'", "")
    track = track.replace('"', "")
    track = track.replace("_", "")
    # removes anything inside ()
    track = sub("\([^\(|^\)]+\)", "", track)
    # removes anything inside []
    track = sub("\[[^\[|^\]]+\]", "", track)
    # removes feat. ...
    track = sub("[fF]eat[\s\S]+", "", track)
    track = track.strip()
    # removes anything thats not a letter or number
    # f = findall('[\w|\d|\ ]+', track)
    # track = ' '.join(f)

    return track


def format_title(s, paren=False):
    # find words, only letters, without ext
    # removes feat. ...
    s = sub("[fF]eat[\s\S]+", "", s)
    if paren:
        # removes anything inside ()
        s = sub("\([^\(|^\)]+\)", "", s)
        # removes anything inside []
        s = sub("\[[^\[|^\]]+\]", "", s)

    s = sub("(\.flac|\.m4a|\.wav)", "", s)
    s = sub("['\"]", "", s)
    formatted = " ".join(findall("[a-zA-Z]+", s)).strip()
    formatted = formatted.replace("  ", " ")
    return formatted


def format_list(l) -> str:
    s = ""
    for g in l:
        s += g + ", " * (len(l) > 1 and g != l[-1])
    print(type(s))
    return s

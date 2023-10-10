#!/usr/bin/env python3
"""This script downloads rss feeds and stores them in a maildir"""

# Copyright(C) 2015 Edgar Thier
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import os
import fcntl
import mailbox
import feedparser
import sys
import getopt
import time
from datetime import date, datetime, timedelta
import json
import getpass
import urllib.request
import html2text
import html


class defaults:
    """Contains global default values"""
    maildir = os.path.expanduser("~/.mail/rss/")
    config = os.path.expanduser("~/.config/rss2maildir.json")
    cache = os.path.expanduser("~/.cache/rss2mail/")
    maildir_cache = os.path.expanduser("~/.mail/rss.rss2maildircache")
    use_single_maildir = False
    mail_sender = "rss2mail"
    mail_recipient = getpass.getuser() + "@localhost"
    days_to_remember = 14


class rss_feed:
    """"""
    def __init__(self):
        self.name = ""
        self.url = ""
        self.maildir = ""
        self.days_to_remember = 0
        self.cache = None


def load_config():
    """Load configuration from JSON"""
    json_data = open(defaults.config).read()
    config = json.loads(json_data)

    if "use_single_maildir" in config["general"]:
        defaults.use_single_maildir = config["general"]["use_single_maildir"]
        defaults.cache = defaults.maildir_cache
        if not isinstance(defaults.use_single_maildir, bool):
            print("use_single_maildir has to be true or false")
            exit(1)

    if "days_to_remember" in config["general"]:
        dtr = config["general"]["days_to_remember"]
        if not isinstance(dtr, int):
            print("days_to_remember has to be integer")
            exit(1)
        defaults.days_to_remember = dtr

    if "sender" in config["general"]:
        defaults.mail_sender = config["general"]["sender"]
        if not isinstance(defaults.mail_sender, str):
            print("sender has to be a string")
            exit(1)

    if "recipient" in config["general"]:
        defaults.mail_recipient = config["general"]["recipient"]
        if not isinstance(defaults.mail_recipient, str):
            print("recipient has to be a string")
            exit(1)

    if "cache" in config["general"]:
        defaults.cache = config["general"]["cache"]
        if not isinstance(defaults.cache, str):
            print("cache has to be a string")
            exit(1)

    if "maildir" in config["general"]:
        defaults.maildir = config["general"]["maildir"]
        if not isinstance(defaults.cache, str):
            print("maildir has to be a string")
            exit(1)

    feed_list = []

    for single_feed in config["feeds"]:
        feed = rss_feed()
        feed.name = single_feed["name"]
        feed.url = single_feed["url"]

        if defaults.use_single_maildir:
            feed.maildir = defaults.maildir
        else:
            feed.maildir = defaults.maildir + "." + feed.name

        if 'maildir' in single_feed:
            feed.maildir = single_feed["maildir"]

        feed.days_to_remember = defaults.days_to_remember
        if 'days_to_remember' in single_feed:
            dtr = single_feed["days_to_remember"]
            if not isinstance(dtr, int):
                print("feed.days_to_remember has to be integer")
                exit(1)
            feed.days_to_remember = dtr

        feed.links = False
        if 'links' in single_feed:
            feed.links = single_feed["links"]
            if not isinstance(feed.links, bool):
                print("feed.links has to be true or false")
                exit(1)

        if not feed.name:
            print("Missing feed name. Aborting...")
            exit(1)
        if not feed.url:
            print("Missing feed url. Aborting...")
            exit(2)
        feed_list.append(feed)

    return feed_list

def update_maildir(maildir, rss, origin, links):
    """
    Creates or updates the given maildir and fills it with the messages
    maildir - Maildir that shall be used
    rss - feedparser entry that shall be converted
    """
    print("Writing {0}".format(rss.title))
    mbox = mailbox.Maildir(maildir)
    mbox.lock()
    try:
        msg = mailbox.MaildirMessage()

        msg['From'] = origin
        msg['To'] = defaults.mail_recipient
        msg['Subject'] = html.unescape(rss.title)

        dt = rss_item_datetime(rss)
        msg.__setitem__('Date', f'{dt:%a}, {dt.day} {dt:%b} {dt.year} {dt:%H}:{dt:%M}:{dt:%S} +0000')

        message_texts = []

        if "description" in rss:
            converter = html2text.HTML2Text()
            if not links:
                converter.ignore_links = True
                converter.ignore_images = True
            txt = converter.handle(rss.description)
            message_texts.append(txt)

        if "link" in rss:
            message_texts.append(rss.link)

        message = "\n".join(message_texts)

        msg.set_payload(message.encode('utf-8'))

        mbox.add(msg)
        mbox.flush()

    finally:
        mbox.unlock()


def load_cache(rss):
    """Load cache file and fill rss feeds with their values"""

    filename = os.path.expanduser(defaults.cache) + "/" + rss.name + ".json"
    if os.path.isfile(filename):
        with open(filename, 'rb') as input_file:
            data = input_file.read()
            rss.cache = json.loads(data)


def save_object(obj, filename):
    """Save object to given file"""
    if obj is None:
        return
    try:
        with open(filename, 'wb') as output:
            output.write(obj.encode())
    except Exception as e:
        print(" - ERROR saving to {0}: {1}".format(filename, e))


def expire(cache, dtr):
    today = date.today()
    threshold = timedelta(days=dtr)
    res = {}

    for l, d in cache.items():
        dt = datetime.strptime(d, "%Y-%m-%d").date()
        dist = today - dt
        if dist < threshold:
            res[l] = d

    return res

def write_cache(rss):
    if rss.cache == None:
        return

    cpath = os.path.expanduser(defaults.cache)
    if not os.path.exists(cpath):
        os.makedirs(cpath)

    cache = expire(rss.cache, rss.days_to_remember)

    filename = cpath + "/" + rss.name + ".json"
    jdata = json.dumps(cache)
    save_object(jdata, filename)


def item_id(item):
    try:
        id = None
        if "id" in item:
            id = item.id
        else:
            id = item.link

        # some websites flip http/https in feeds, so cut them out
        id = id.removeprefix("https:")
        id = id.removeprefix("http:")
        return id
    except Exception as e:
        print(f"item_id, exception: {e}, item = {item}")
        sys.exit(20)

def rss_item_datetime(item):
    dt = None
    if "published_parsed" in item:
        dt = item.published_parsed
    elif "updated_parsed" in item:
        dt = item.updated_parsed

    if dt == None:
        return datetime.now()

    return datetime.fromtimestamp(time.mktime(dt))

def extract_new_items(new_list, feed):
    """Extract new feed entries
    new_list - list from which new entries shall be extracted
    old_list - list whith which new_list is compared

    returns array of entries found in new_list and not in old_list
    """

    if not new_list:
        print("Empty list!")
        return []

    today = date.today()
    threshold = timedelta(days=feed.days_to_remember)

    new_entries = []
    for item in new_list:
        new_id = item_id(item)
        if feed.cache == None or new_id not in feed.cache:

            dt = rss_item_datetime(item).date()
            delta = today - dt
            if delta < threshold:
                new_entries.append(item)

    return new_entries


def download_feed(feed):
    """
    feed - rss_feed object
    """

    if feed.url is None:
        print("No viable url found! Aborting feed...")
        return False

    print("Downloading '{0}'...".format(feed.url))
    user_agent = 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.0.7) Gecko/2009021910 Firefox/3.0.7'

    feedObject = None

    try:
        headers = {'User-Agent': user_agent, }
        request = urllib.request.Request(feed.url, None, headers)
        response = urllib.request.urlopen(request, None, timeout=10)
        data = response.read()
        xml = data.decode('utf-8')
        feedObject = feedparser.parse(xml)
    except Exception as e:
        print("Unable to download feed {0}: {1}".format(feed.url, e))
        return

    if not feedObject:
        print("Unable to download {0}".format(feed.url))
        return

    new_entries = extract_new_items(feedObject.entries, feed)

    maildir = feed.maildir

    if new_entries:
        if feed.cache == None:
            feed.cache = {}

        for item in new_entries:
            update_maildir(maildir, item, feedObject['feed']['title'], feed.links)
            iid = item_id(item)
            dt = rss_item_datetime(item).date()
            sdt = dt.strftime("%Y-%m-%d")
            feed.cache[iid] = sdt


def print_help():
    """Prints help text and arguments"""
    print("""{0}

Download rss feeds and convert them to maildir entries.
Options:
\t-h print help text
\t-c define config to use [default: {1}]
\t-t define cache directory to use [default: {2}]
""".format(sys.argv[0],
           defaults.config,
           defaults.cache))

def lock_file():
    fname = "/tmp/rss2maildir.lock"
    handle = open(fname, 'w')
    try:
        fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except IOError:
        return None


def main(argv):
    """Entry point"""

    try:
        opts, args = getopt.getopt(argv,
                                   "hc:t:",
                                   ["help", "config=", "cache="])
    except getopt.GetoptError:
        print_help()
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print_help()
            sys.exit()
        elif opt in ("-c", "--config"):
            defaults.config = arg
        elif opt in ("-t", "--cache"):
            defaults.cache = arg

    lock = lock_file()
    if lock == None:
        print("Another copy of rss2mailbox is running")
        sys.exit()

    feeds = load_config()

    for feed in feeds:
        load_cache(feed)
        download_feed(feed)
        write_cache(feed)

if __name__ == "__main__":
    main(sys.argv[1:])

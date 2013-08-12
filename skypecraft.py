#!/usr/bin/env python
#
# Skypecraft
# https://github.com/kirov/skypecraft
#
# Copyright (c) 2012-2013 Evgeniy Kirov
# See the file LICENSE for copying permission.

from datetime import datetime
import rconite
import re
import Skype4Py
import sys
import tailer
import textwrap

import StringIO
import os
import ConfigParser

import settings

reload(sys)
sys.setdefaultencoding('utf-8')


class Daemon(object):

    skype_commands = ['players', 'call', 'kick', 'ban', 'jail']
    minecraft_commands = ['call']

    def __init__(self):
        config = StringIO.StringIO()
        config.write('[dummysection]\n')
        config.write(open(settings.MINECRAFT_SERVER_LOCATION + 'server.properties').read())
        config.seek(0, os.SEEK_SET)
        cp = ConfigParser.ConfigParser()
        cp.readfp(config)
        self.rconport = cp.get('dummysection', 'rcon.port')
        self.serverport = cp.get('dummysection', 'server-port')
        self.rconpassword = cp.get('dummysection', 'rcon.password')

        self.log('Hello!')
        self.setup_skype()
        self.setup_rcon()
        self.setup_server_log()

    def run(self):
        for line in tailer.follow(self.server_log):
            self.on_server_log(line)

    def stop(self):
        self.log('Stopping...')
        self.server_log.close()

    def log(self, message, level=0):
        log_levels = {
            0: 'INFO',
            1: 'WARNING',
            2: 'ERROR'
        }
        print '%s [%s] %s' % (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            log_levels[level],
            message
        )
        sys.stdout.flush()

    def sanitize(self, line):
        # line = re.compile("\x1f|\x02|\x12|\x0f|\x16|\x03(?:\d{1,2}(?:,\d{1,2})?)?", re.UNICODE).sub('', line)
        line = re.compile("(?:\xA7.)|(?:\x1B\[[\d;]*m)", re.UNICODE).sub('', line)
        return line

    def setup_skype(self):
        self.skype = Skype4Py.Skype()
        self.skype.Attach()
        self.skype.OnMessageStatus = lambda *a, **kw: self.on_skype_message(*a, **kw)
        self.skype.OnCallStatus = lambda *a, **kw: self.on_skype_call(*a, **kw)
        self.skype_chat = self.skype.Chat(settings.SKYPE_CHAT_NAME)
        self.log('Attached to Skype')

    def setup_rcon(self):
        self.rcon = rconite.connect(
            'localhost',
            self.rconport,
            self.rconpassword
        )
        self.log('Connected to RCon')
        self.skype_chat.SendMessage('Minecraft Server running on port ' + self.serverport)

    def setup_server_log(self):
        self.server_log = open(settings.MINECRAFT_SERVER_LOCATION + 'server.log')
        self.log('Opened server.log')

    def send_skype(self, msg):
        msg = str(msg.decode('utf-8', errors='ignore'))
        self.skype_chat.SendMessage(msg)
        self.log('Sent to Skype: %s' % msg)

    def send_rcon(self, msg):
		if settings.BUKKIT_PLUGIN_INSTALLED == 'yes':
			bpi = 'skype'
		else:
			bpi = 'say'
		for part in textwrap.wrap(msg, 60):
			part = part.encode('utf-8')
			self.rcon.command('%s %s' % (bpi, part))
		self.log('Sent to Minecraft: %s' % msg)

    def on_skype_message(self, msg, status):
        if status != 'RECEIVED':
            return
        if msg.ChatName != settings.SKYPE_CHAT_NAME:
            return
        msg.MarkAsSeen()
        parts = msg.Body.split()
        if parts and parts[0] in self.skype_commands:
            command = parts[0]
            args = parts[1:]
            self.log('Someone has sent a command "%s"' % command)
            if getattr(self, 'command_%s' % command)(*args):
                return
        self.send_rcon(u'[Skype] <%s> %s' % (msg.Sender.FullName, msg.Body))

    def on_skype_call(self, *args, **kwargs):
        self.skype.Mute = True

    def on_server_log(self, line):
        line = self.sanitize(line).decode(settings.MINECRAFT_SERVER_LOG_ENCODING)
        # checking if user command
        match = re.compile('^[0-9\-\s:]{20}\[INFO\]\s\<.+\>\s(\w+)(\s.+)?$').match(line)
        if match and match.groups()[0] in self.minecraft_commands:
            command = match.groups()[0]
            args = match.groups()[1]
            args = args.split() if args else []
            self.log('Someone has sent a command "%s"' % command)
            if getattr(self, 'command_%s' % command)(*args):
                return
        # checking if this is a message from user
        match_base = '^[0-9\-\s:]{20}\[INFO\]\s(%s)$'

        match_vars = [
            '\<.+\>\s.+',
        ]

        if settings.SERVER_MESSAGE == 'on':
            match_vars.append('\[Server\]\s.+')
        if settings.BAN_MESSAGE == 'on':
            match_vars.append('.+\:\sBanned player\s.+')
            match_vars.append('Player\s.+\sbanned\s.+\sfor\s.+')
        if settings.KICK_MESSAGE == 'on':
            match_vars.append('.+\:\sKicked player\s.+')
            match_vars.append('Player\s.+\skicked\s.+\sfor\s.+')
        if settings.JOIN_MESSAGE == 'on':
            match_vars.append('.+\[\/.+\]\slogged\sin.+')
        if settings.LEAVE_MESSAGE == 'on':
            match_vars.append('.+\sleft\sthe\sgame.')


        matchjoin = match_base % '|'.join(map(lambda a: '(?:%s)' % a, match_vars))

        match = re.compile(matchjoin).match(line)

        if match:
            text = match.groups()[0] 
            text = re.compile('.\sWith reason\:$').sub('', text)
            text = re.compile('\[\/.+\]\slogged\sin.+').sub(' joined the game', text)
            self.send_skype(text)

    def command_players(self, *args):
        line = self.rcon.command('list')
        line = self.sanitize(line)
        line = line.replace('online:', 'online: ')
        self.send_skype(line)
        return True

    def command_call(self, *args):
        if settings.CALL_COMMAND != 'on':
            return False
        try:
            self.skype.PlaceCall(settings.SKYPE_CHAT_NAME)
        except ValueError:
            pass
        return True

    def command_kick(self, *args):
        if len(args) != 1:
            return False
        elif settings.KICK_COMMAND != 'on':
            return False
        self.rcon.command("kick %s" % args[0])
        return True

    def command_ban(self, *args):
        if len(args) != 1:
            return False
        elif settings.BAN_COMMAND != 'on':
            return False
        self.rcon.command("ban %s" % args[0])
        return True

if __name__ == '__main__':
    d = Daemon()
    try:
        d.run()
    except KeyboardInterrupt, e:
        d.stop()

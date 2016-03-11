#!/usr/bin/env python
from _socket import error
from telnetlib import *
from socket import *
import re
import sys
import operator
import json
import Poll
from time import gmtime, strftime, sleep
from string import Template
import StaticTriggers

def ClientInfo(username=None,password=None,channel=None,*args,**kwargs):
    HOST=kwargs.get('HOST','irc.twitch.tv')
    PORT=int(kwargs.get('PORT','6667'))
    NICK = kwargs.get('NICK', username.encode("UTF-8"))
    PASS = kwargs.get('PASS',password.encode("UTF-8"))
    CHANNELS = [channel.encode("UTF-8")]
    #CHANNELS = filter(lambda x: x.startswith('#'), args)
    #CHANNELS = map(lambda x: x.lower(), CHANNELS)
    return HOST, PORT, NICK.lower(), PASS, CHANNELS


def TwitchSignon(HOST,PORT,NICK,PASS,CHANNELS):
    print("Connecting to Twitch ircd")
    tn = Telnet(HOST,PORT)

    USER='ppBot: python poll bot'

    print("Logging in as {0} with password {1}".format(NICK,PASS))
    tn.write('PASS ' + PASS + '\n')
    tn.write('NICK ' + NICK + '\n')
    t_str = tn.read_until('tmi.twitch.tv 001 ',60)

    # MOTD
    tn.read_until(':You are in a maze of twisty passages, all alike.\r\n')

    # end of MOTD
    tn.read_until(':tmi.twitch.tv 376 ')

    helo_line = tn.read_until(':>\r\n')


    idx = helo_line.find(' ')
    
    myname = helo_line[:idx]
    tn.msg("my name = {0}",myname)

    tn.write('USER ' + USER + '\r\n')

    for chan in CHANNELS:
        tn.write('JOIN ' + chan + '\r\n')

    return (tn, myname)


class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
#     else: 
#        cls._instances[cls].__init__(*args, **kwargs)
# everytime class is called
        return cls._instances[cls]


class LogHistory(object):
    __metaclass__ = Singleton
    
    def __init__(self):
        self.fp = open('poll.log','a')
        self.fp.write(self.str_timestamp() + 'LogHistory.__init__ \n')

    def __del__(self):
        self.fp.close()

    def log(self,str):
        self.fp.write(self.str_timestamp() + str)

    def str_timestamp(self):
        return strftime("\n%a, %d %b %Y %H:%M:%S ", gmtime())


class PollInfo(Poll.PollInfo):

    def __init__(self,tn,Channel):
        self.all_users = set()
        self.super_users = set()
        Poll.PollInfo.__init__(self,Channel)
        self.tn = tn

    def add_oper(self,user):
        self.super_users.add(user)
    
    def rem_oper(self,user):
        self.super_users.discard(user)

    def add_users(self,*users):
        for iUser in users:
            if iUser not in self.all_users:
                self.all_users.add(iUser)

    def rem_user(self,user):
        if user in self.all_users:
            self.all_users.discard(user)

    def user_poll_msg(self,user,pmsg):
        Poll.PollInfo.user_poll_msg(self,user,pmsg)

    def can_user_create_poll(self,user,channel=None):
        return True

    def on_poll_message(self,msg):
        print('on_poll_msg', msg)
        self.tn.write(msg + '\n')

class RequireChannel(object):
    def __init__(self,func):
        self.func = func

    def __call__(*args,**kwargs):
        if 'channel' in kwargs:
            self.func(*args,**kwargs)

class ChannelInfo(object):
    def __init__(self):
        self.PollInfo = {}
        self.all_channels = set()

    def Channel(self,channel):
        if channel not in self.all_channels:
            self.all_channels.add(channel)
            self.PollInfo.update({channel:PollInfo(self.tn,channel)})
        return self.PollInfo[channel]


class MessageHandler(ChannelInfo):
    def __init__(self,tn):
        self.tn = tn
        ChannelInfo.__init__(self)

    def reply_to_channel(self,channel,msg):
        self.tn.write('PRIVMSG {0} :{1}\r\n'.format(channel,msg))

    def ProcessChannelMessage(self,user,channel,msg):
        LogHistory().log(user + ' ' + channel + ' ' + msg)

        if msg in StaticTriggers.triggers:
            reply_msg = StaticTriggers.triggers[msg]
            self.reply_to_channel(channel,reply_msg)
            return

        if not msg or msg[0] != '!':
            return

        self.Channel(channel).user_poll_msg(user,msg)

    def ProcessOper(self,channel,mode,user):
        c = self.Channel(channel)
        if mode == '+o':
            c.add_oper(user)
        elif mode == '-o':
            c.rem_oper(user)

    def ProcessOnJoin(self,channel,user):
        c = self.Channel(channel)
        LogHistory().log(user + ' joined ' + channel)

        c.add_users([user])

    def ProcessUserAction(self,user,action,channel):
        c = self.Channel(channel)

        if action == 'PART':
            c.rem_user(user)
        elif action == 'JOIN':
            c.add_users(user)
        else:
            print('unknown action', action)

    def ProcessNames(self,channel,users):
        c = self.Channel(channel)
        c.add_users(*users.strip().split(' '))

    def ProcessNamesFinished(self,channel):
        c = self.Channel(channel)
        print('PollInitialiazed', channel)

    def ProcessUserMessage(self,user,msg): 
        print(user, msg)

    def ProcessPing(self,msg):
        self.tn.write('PONG ' + msg + '\n')



    

### main handler creates reg-exp objects for all the message types.  This is a bit overkill, and worse, if 
##  the regular expressions are too general that they become ambigious, it is not deterministic which expression
##  object will take the match.  Luckily the twitch ircd server has a very limited set of commands, and this
##  shouldn't be an issue.

class ConnectionHandler(MessageHandler):
    def __init__(self,tn,name):
        self.tn = tn
        self.name = name
        MessageHandler.__init__(self,tn)


        #IRC keep-alive
        ping_re = re.compile(r'PING (?P<msg>.*)\r\n')
        #Private messages
        pmsg_re = re.compile(r':(?P<user>[\w]{2,15})!\1@\1.tmi.twitch.tv PRIVMSG ' + name + r' :(?P<msg>.*)\r\n')
        channel_re = re.compile(r':(?P<user>[\w]{2,15})!\1@\1.tmi.twitch.tv PRIVMSG (?P<channel>#\w+) :(?P<msg>.*)\r\n')
        action_re = re.compile(r':(?P<user>[\w]{2,15})!\1@\1.tmi.twitch.tv (?P<action>JOIN|PART) (?P<channel>#\w+)\r\n')
        #Operator and Moderator messages
        oper_re = re.compile(r':jtv MODE (?P<channel>#\w+) (?P<mode>[\-\+][ovm]) ?(?P<user>\w*)\r\n')

        #Names command
        names_pattern = Template(r':$User.tmi.twitch.tv 353 $User = (?P<channel>#\w+) :(?P<users>.*)\r\n').substitute(User=name)
        #End of Names Command
        names_end_pattern = Template(r':$User.tmi.twitch.tv 366 $User (?P<channel>#\w+) :End of /NAMES list\r\n').substitute(User=name)
        #User in channel on join
        jchan_pattern = Template(r':$User.tmi.twitch.tv 352 $User (?P<channel>#\w+) (?P<user>\w+) $User.tmi.twitch.tv tmi.twitch.tv \1 H :0 \1\r\n').substitute(User=name)

        names_re = re.compile(names_pattern)
        names_end_re = re.compile(names_end_pattern)
        jchan_re = re.compile(jchan_pattern)

        ChannelRE = [('PING',ping_re,self.ProcessPing),                    ('USER MSG',pmsg_re,self.ProcessUserMessage),
                        ('USER MODE',oper_re, self.ProcessOper),               ('/NAMES',names_re, self.ProcessNames), 
                        ('/NAMES END',names_end_re, self.ProcessNamesFinished),('JOIN',jchan_re,self.ProcessOnJoin),
                        ('USER ACTION',action_re,self.ProcessUserAction),      ('CHAN MSG',channel_re,self.ProcessChannelMessage)]


        self.TextRE = map(lambda x: operator.getitem(x,0), ChannelRE)
        self.ListRE = map(lambda x: operator.getitem(x,1), ChannelRE)
        self.FuncRE = map(lambda x: operator.getitem(x,2), ChannelRE)

        self.REHash = dict(list(enumerate(self.FuncRE)))

    def main_handler(self):
        tn = self.tn
        while (True):
            try:
                idx, mo, text = tn.expect(self.ListRE,15)

            except EOFError:
                LogHistory().log('Connection Closed')
                raise EOFError

#            print(idx,mo,text)

            if (idx < 0 or not mo):
                if text != '':
                    LogHistory().log('unkown msg ' + text)
            else:
                Func = self.REHash.get(idx)
                Func(**mo.groupdict())
                


def main(*args,**kwargs):
    rcount = 0
    SessionInfo = ClientInfo(*args,**kwargs)
    StaticTriggers.initialize()

    while True:
        try:
            ConnectionInfo = TwitchSignon(*SessionInfo)
            ch = ConnectionHandler(*ConnectionInfo)
            print("Entering main-loop handler...")
            rcount = 0
            ch.main_handler()
        except (EOFError, error, timeout):
            rcount += 1
            if (rcount > 5):
                break
            print('Disconnected, trying again in 10 seconds. . .')
            sleep(10)
    print("Failed to connect after 5 attempts, exiting.")



if __name__ == '__main__':
    kwarg = {}
    with open('account.json','r') as fileObj:
        acc_info = json.load(fileObj)
        assert acc_info.get('username')
        assert acc_info.get('password')
        assert acc_info.get('channel')
        kwarg.update(acc_info)
    split_arg = map(lambda x: x.split('='), sys.argv[1:len(sys.argv)])
    filter_kwarg = filter(lambda x: len(x) == 2, split_arg)
    args = filter(lambda x: len(x) != 2, split_arg)
    args = [item for sublist in args for item in sublist]
    kwarg.update(dict(filter_kwarg))
    main(*args,**kwarg)



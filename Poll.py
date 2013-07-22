#!/usr/bin/env python
import re
import string
import threading
from string import Template

PollStatus_initialized = 'initialized'
PollStatus_ready   = 'ready'
PollStatus_created = 'created'
PollStatus_running = 'running'
PollStatus_report  = 'reporting'
PollStatus_sleeping = 'sleeping'

class PollInfo(object):
	re_poll_yesno = re.compile(r'^!poll (?P<question_prefix>Can|Should|Did|Will|Do|Does) (?P<question>[\w ]{3,35})\?$',re.IGNORECASE)
	re_poll_binary = re.compile(r'^!poll (?P<option1>[\w]{3,9})(, or| or|,) (?P<option2>[\w]{3,9})[?.\n]$')
	re_poll_q_part = re.compile(r'^!poll (?P<question>[\w ]{3,25})[\?:]')
	re_poll_opt_part = re.compile(r'\b(?P<option>[\w ]{2,16})[?.|\b]')

	poll_reply_tmpl = Template('PRIVMSG $Channel : Poll Started! $Question: $OptionsAll?')
	poll_end_tmpl = Template('PRIVMSG $Channel : Poll has Ended. $Option won with $Count% of $Total votes.')
	poll_end_tie_tmpl = Template('PRIVMSG $Channel : Poll Ended in a tie. $Option each had $Count% of $Total votes.')

	pollTimeOut = 35.0

	def __init__(self,Channel):
		self.status = 'initialized'
		self.users_voted = set()
		self.channel = Channel

	def user_poll_msg(self,user,pmsg):
		if self.status == PollStatus_ready or self.status == PollStatus_initialized:
			pargs = self.start_poll(pmsg)
			if pargs == None:
				return None
		elif self.status == PollStatus_created:
			try:
				self.pcounter(user,pmsg)
			except:
				pass
	
		else:
			print 'unknown status', self.status

			
		pass

	def can_user_create_poll(self,user):
		'''
Overload to restrict poll creation such as only opers or not allowing the most recent.
		
		'''
		return True
		pass

	def construct_poll_from_msg(self,user_msg):
		'''
user_msg must have one of the following forms:
!poll A sample question ending in a question mark?
!poll OneWord, andShort.
!poll A full blown question with: one answer, two answers, and multiple words, seperated by commas.
The two forms create two option answers, yes, no, or simple one word answers.  The last form will split the option part at commas or question mark boundries.  Further reg expressions break each option into a list of whole words.  The list is converted into a set of words, and for each poll option, the lists are XORed to find a unique set of words.  The unique set of words is then takes the intersection of each option set.  In the end, a random unique word is selected for each option represent that option as the !vote command for the vote counter
		'''
		popt = ()
		pquestion = ''
		RO = self.re_poll_yesno.match(user_msg)
		if RO:
			print 'question type yesno'
			pquestion = RO.groupdict()['question_prefix'] + ' ' + RO.groupdict()['question']
			popt = ('yes','no')
			kopt = ('!yes','!no')
			return {'question':pquestion, 'options':popt, 'key_options':kopt}

		RO = self.re_poll_binary.match(user_msg)
		if RO:
			print 'question type binary'
			popt = (RO.groupdict()['option1'],RO.groupdict()['option2'])
			kopt = ('!' + RO.groupdict()['option1'],'!' + RO.groupdict()['option2'])
			if 'question' not in RO.groupdict():
				pquestion = '{0}, or {1}'.format(*kopt)
			else:
				pquestion = RO.groupdict()['question']

			return {'question':pquestion, 'options':popt, 'key_options':kopt}

		RO = self.re_poll_q_part.search(user_msg)
		if RO:
			print 'question type multi'
			pquestion = RO.groupdict()['question']
			popt_str = user_msg[RO.end():]
			popt = popt_str.split(',')

		else:
			return None

		if len(popt) < 2:
			print 'not enough options in multipart question'
			return None

		popt = map(lambda x: x.strip(string.punctuation + string.whitespace).lower(),popt)
		if (min( map(lambda x: len(x), popt) ) < 4):
			print 'after sanitising, options were too small', popt
			return None

		ListOfListOfKeyW = map(lambda (x): re.split(r'\b([a-z]+)\b',x),popt)  
		#### split options into list of whole words

		ListOfListOfKeyW = [[word for word in OptList if len(word) > 3] for OptList in ListOfListOfKeyW]
		## ignore words of length less than 3

		ListOfListOfKeyW = [[word for word in OptList  if not (re.search(r'[\d\b\!{}\[\] ]',word) or not word or len(word) < 4)] for OptList in ListOfListOfKeyW]

		# exclude invalid characters
		list_of_word_set = [set([word for word in OptList]) for OptList in ListOfListOfKeyW]

		# find unique words accross list of sets
		unique_word = reduce(lambda x,y: x.symmetric_difference(y),list_of_word_set)

		if len(unique_word) < len(popt):
			return None
		
		# intersect unique set with list of sets
		unique_option_word_list = map(lambda x: x.intersection(unique_word), list_of_word_set)

		OptionVoteKeyWordList = []

		for idx,iSet in enumerate(unique_option_word_list):
			import random
			sl = len(iSet) 
			if sl == 0:
				print 'no suitable unique words found to make vote !options with'
				print ListOfListOfKeyW
				print list_of_word_set, 'No unique'
				print unique_word
				print unique_option_word_list
				return None

		
			ridx = random.choice(list(iSet))
			OptionVoteKeyWordList.append(ridx)
			pos = popt[idx].find(ridx)
			if pos == -1:
				print 'odd, couldn\'t find ', ridx, ' in ', popt[idx]
				print popt[idx]
				return None
			newstr = popt[idx][:pos] + '!' + popt[idx][pos:]
			popt[idx] = newstr


		if len(popt) != len(OptionVoteKeyWordList):
			print '..lists should be same size . . .'
			return None

		kopt = map(lambda x: '!' + x, OptionVoteKeyWordList)

		return {'question':pquestion, 'options':popt, 'key_options':kopt}

	def start_poll(self,poll_str,User=None,Channel=None):
		if self.status != PollStatus_initialized and self.status != PollStatus_ready:
			return None

		if User != None:
			if not self.can_user_create_poll(User):
				return None

		pollvar = self.construct_poll_from_msg(poll_str)
		if pollvar == None:
			return None

		def construct_poll_response(question,options,key_options,**kwargs):
			'''creates templated string, and constructs function to respond to the channel the vote was initiated.  Also created RE objects used in matching !vote commands with option'''
			
			assert isinstance(options,list) or isinstance(options,tuple)
			assert isinstance(key_options,list) or isinstance(options,tuple)
			assert len(options) == len(key_options)

			OptionREList = [re.compile(key_opt,re.IGNORECASE) for key_opt in key_options]

			OptionsAll = ''

			for s_opt in options:
				if OptionsAll != '':
					OptionsAll = OptionsAll + ', '
				OptionsAll = OptionsAll + s_opt

			poll_reply = self.poll_reply_tmpl.substitute({'Channel':self.channel, 'Question':question, 'OptionsAll':OptionsAll})

			self.queueMsg(poll_reply)
			self.queueMsg(self.on_poll_end,self.pollTimeOut)

			return OptionREList

		REOptions = construct_poll_response(**pollvar)

		self.pquestion = pollvar['question']
		self.poptions = pollvar['options']
		self.vote_tally = [0] * len(REOptions)

		def poll_counter(re_options,vote_counter):
			users_voted = set()

			def poll_result(user,msg):
				if user in users_voted:
					print user, 'already voted'
					return 0

				for i,re_obj in enumerate(re_options):
					if re_obj.match(msg):
						vote_counter[i] = vote_counter[i] + 1
						print user, 'voted', msg
						users_voted.add(user)
						return 1

				print 'no match', user, msg

			return poll_result

		self.status = PollStatus_created
		self.pcounter = poll_counter(REOptions,self.vote_tally)


	def on_poll_end(self):
		total_votes = sum(self.vote_tally)

		if total_votes > 0:
			max_vote = max(self.vote_tally)

			vote_list = zip(self.vote_tally,self.poptions)
			vote_won = filter(lambda x: x[0] == max_vote,vote_list)

			vote_won = map(lambda x: (round(float(x[0])/(total_votes/100.0),1),x[1]),vote_won)

			print self.pquestion
			print 'vote tally', vote_won, total_votes


			poll_reply_msg = ''

			pmDict = {'Channel':self.channel,'Count':vote_won[0][0],'Total':total_votes}
			if len(vote_won) == 1:
				pmDict.update({'Option':vote_won[0][1]})
				poll_reply_msg = self.poll_end_tmpl.substitute(pmDict)
			else:
				AggOptions = ''
				for iOpt in range(len(vote_won)):
					AggOptions = AggOptions + vote_won[iOpt][1] + ' '
				pmDict.update({'Option':AggOptions})
				poll_reply_msg = self.poll_end_tie_tmpl.substitute(pmDict)

			self.queueMsg(poll_reply_msg,0.0)
			self.status = PollStatus_report
		else:
			self.status = PollStatus_sleeping

		self.on_poll_stop()

	def on_poll_stop(self):
		if hasattr(self,'pcounter'):
			del self.pcounter
		if hasattr(self,'vote_tally'):
			del self.vote_tally
		if hasattr(self,'pquestion'):
			del self.pquestion
		if hasattr(self,'poptions'):
			del self.poptions

		self.queueMsg(self.on_sleep_over,61.0)

	def on_sleep_over(self):
		self.status = PollStatus_ready

	def on_poll_message(self,msg):
		print 'Timer Fire'
		print msg

	def queueMsg(self,t, delay = 0.0):
		from threading import Timer
		import types
		
		if isinstance(t,types.FunctionType) or isinstance(t,types.MethodType):
			T = Timer(delay,t)
			T.start()
			return T
		
		if isinstance(t,str):
			T = Timer(delay,self.on_poll_message,args=(t,))
			T.start()
			return T
		
		print 'Q msg fail', type(t)
		return None


if __name__ == '__main__':
	import random
	import string
	import time
	import copy

	mypoll = PollInfo('#test')
	User='testuser1'
	def NameGenerator(ncount):
		user_list = []
		for i in range(0,ncount):
			user_list.append( 'User' + str(i))


		while True:
			yield random.choice(user_list)

	NameGen = NameGenerator(4)

	try:
		while True:
#			print mypoll.status
			user_msg = raw_input('cmd> ')
			mypoll.user_poll_msg(NameGen.next(),user_msg)
	except EOFError:
		pass
	

from glob import glob
import string
import os


triggers = {}

def add_trigger(triggername,triggercontents):
    triggers[triggername] = triggercontents

def del_trigger(triggername):
    triggers.pop(triggername)

def open_trigger_file(triggerfile):
    """
    Expects a filename.  Returns a 2-element tuple, with the first
    element of the tuple being the filename with the extension removed.
    The second tuple is the contents of the file
    """

    print("Reading file {0}".format(triggerfile))
    basedir, basename = os.path.split(triggerfile)
    trigger = '!' + string.replace(basename,".txt","")
    contents = ""

    with open(triggerfile,'r') as f: 
        contents = f.read()

    contents = contents.strip()

    return (trigger,contents)
    

def load_triggers():
    list_files = glob('triggers/*.txt')
    for tFile in list_files:
        trigger, contents = open_trigger_file(tFile)
        add_trigger(trigger,contents)

def triggers_available():
    cmds = []
    for key in triggers.keys():
        cmds.append(key)

    return ", ".join(cmds)


def initialize():
    load_triggers()
    add_trigger("!commands",triggers_available())

    for key,val in triggers.items():
        print("Trigger: {0} - {1}".format(key,val))


if __name__ == '__main__':
    initialize()



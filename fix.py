import re, sys

def fixhex(matchobj):
    if ">" in matchobj.group(2):
        return "#{0}{1}{2}".format(matchobj.group(1), matchobj.group(2), matchobj.group(3))
    else:
        return "0{0}H{1}".format(matchobj.group(2), matchobj.group(3))

hexmatcher = re.compile("(>)([0-9A-Fa-f]{1,8})(,?)")

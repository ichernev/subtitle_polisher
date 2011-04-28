#!/bin/env python

import pysrt
import logging
import sys  # argv
import os   # remove, rename

logging.basicConfig(level = logging.INFO)

def load_subs(filename):
  return pysrt.SubRipFile.open(filename)
  # fd = open(filename, 'rU')
  # # try to ignore utf-8 BOM
  # if fd.read(3) != '\xef\xbb\xbf':
  #   fd.seek(0)
  # else:
  #   logging.info("Skipping BOM for utf-8. Phew!")

  # return pysrt.SubRipFile.open(file_descriptor = fd)

MIN_GAP = 150
MIN_LEN = 1500
MAX_CHARS = 70

class Summary(object):
  def __init__(self):
    self.gaps_created = 0
    self.prolonged = 0
    self.too_short = 0
    self.too_long = 0

summary = Summary()

def ensure_gap(subs):
  for i in xrange(1, len(subs)):
    cgap = subs[i].start.ordinal - subs[i-1].end.ordinal
    if cgap < MIN_GAP:
      subs[i-1].end -= MIN_GAP - cgap
      logging.info("Creating gap between sub ids: %d %d (was %d)" % \
          (subs[i-1].index, subs[i].index, cgap))
      summary.gaps_created += 1

def check_short(subs):
  for i, sub in enumerate(subs):
    clen = sub.end.ordinal - sub.start.ordinal
    if clen < MIN_LEN:
      can_prolong = True
      if i + 1 < len(subs):
        # check to see if prolonging won't interfere with minimal gap.
        nsub = subs[i + 1]
        cgap = nsub.start.ordinal - sub.end.ordinal

        if cgap - MIN_GAP < MIN_LEN - clen:
          can_prolong = False

      if can_prolong:
        sub.end += MIN_LEN - clen
        logging.info("Prolonged subtitle id %d to min len (was %d)" % \
            (sub.index, clen))
        summary.prolonged += 1
      else:
        logging.warning("Subtitle id %d is too short (len %d ms), and cannot be prolonged" % \
            (sub.index, clen))
        summary.too_short += 1

def check_long(subs):
  for i, sub in enumerate(subs):
    tlen = len(sub.text)
    if tlen > MAX_CHARS:
      logging.warning("Subtitle id %d is too long (len %d chars). Break it down!" % \
          (sub.index, tlen))
      summary.too_long += 1

class Config(object):
  def __init__(self):
    self.fn = None
    self.gap_check = True
    self.short_check = True
    self.long_check = True
    self.inplace_save = False
    self.new_fn = None

  def from_args(self, args):
    print("got args", args)
    ops = True
    for arg in args:
      if arg.startswith('-') and ops:
        if arg == '--':
          ops = False
          continue
        for opt in arg[1:]:
          print("got opt", opt)
          if opt == 'g':
            self.gap_check = True
          elif opt == 's':
            self.short_check = True
          elif opt == 'l':
            self.long_check = True
          elif opt == 'i':
            self.inplace_save = True
          else:
            logging.warning("Unrecognized option %s" % opt)
      elif self.fn == None:
        self.fn = arg
      elif self.new_fn == None:
        self.new_fn = arg
      else:
        logging.warning("Too many arguments")

    if self.fn == None:
      self.usage()

  def usage(self):
    print("timeshift [-gsli] filename [new filename]")
    print("          -g  gap check [on by default]")
    print("          -l  long check [on by default]")
    print("          -s  short check [on by default]")
    print("          -i  inplace save [off by default]")
    sys.exit(-1)

config = Config()
print("%s" % (sys.argv[1:]))
config.from_args(sys.argv[1:])

def save_subs(subs):
  final_name = None
  if config.inplace_save:
    tmp_fn = config.fn + '.new'
    bac_fn = config.fn + '.bac'
    subs.save(tmp_fn)
    try:
      os.remove(bac_fn)
    except OSError, e:
      pass
    os.rename(config.fn, bac_fn)
    os.rename(tmp_fn, config.fn)
    final_name = config.fn
  else:
    new_fn = config.new_fn if config.new_fn else 'fixed.' + config.fn
    try:
      os.remove(new_fn)
    except OSError, e:
      pass
    subs.save(new_fn)
    final_name = new_fn
  logging.info("Subs written to %s" % final_name)

subs = load_subs(config.fn)

ensure_gap(subs)
check_short(subs)
check_long(subs)

save_subs(subs)

print("Summary:")
for k in dir(summary):
  if k.startswith('__'):
    continue
  print("%s: %s" % (k, summary.__getattribute__(k)))

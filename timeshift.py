#!/bin/env python

import pysrt
import logging
import sys  # argv
import os   # remove, rename
import getopt # parsing cmd line options

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

def check_string_length(subs, config):
  res = []

  if config.string_length == "nocheck":
    return res

  for i in range(config.beg, config.end):
    slen = len(subs[i].text)
    if slen > config.max_string_length:
      res.append({'idx': i, 'length': slen, 'msg': 'string too long'})

  return res

def check_duration(subs, config):
  res = []
  
  if config.duration == "nocheck":
    return res

  for i in range(config.beg, config.end):
    dur = subs[i].end.ordinal - subs[i].start.ordinal
    chars_per_sec = len(subs[i].text) / (dur / 1000.0)
    if dur < config.min_duration:
      res.append({'idx': i, 'duration': dur, 'msg': 'short duration'})
    elif chars_per_sec > config.max_chars_per_sec:
      res.append({'idx': i, 'chars_per_sec': round(chars_per_sec), \
          'msg': 'too many characters per second'})

  return res

def check_gap(subs, config):
  res = []

  if config.gap == "nocheck":
    return res

  for i in range(config.beg + 1, config.end):
    gap = get_gap(subs, i)
    if gap < config.min_gap[0]:
      res.append({'idx': i, 'gap': gap, 'msg': 'gap too small'})
    elif gap < config.min_gap[1]:
      res.append({'idx': i, 'gap': gap, 'msg': 'small gap'})

  return res

def check_long(subs, config):
  for i, sub in enumerate(subs):
    tlen = len(sub.text)
    if tlen > MAX_CHARS:
      logging.warning("Subtitle id %d is too long (len %d chars). Break it down!" % \
          (sub.index, tlen))
      summary.too_long += 1

def bsrch(subs, time):
  if subs[-1].end.ordinal < time:
    return len(subs)

  l = -1
  r = len(subs)
  while l + 1 < r:
    m = (l + r) / 2
    # print("subs[%d].end.ordinal == %d < %d" % (m, subs[m].end.ordinal,time))
    if time < subs[m].end.ordinal:
      r = m
    else:
      l = m
  # print("bsrch %d --> %d" % (time, l))
  return r

def get_gap(subs, idx):
  if idx == 0:
    return 5000
  return subs[idx].start.ordinal - subs[idx-1].end.ordinal

def find_big_gap(subs, start, config):
  sub_idx = bsrch(subs, start)
  if sub_idx == 0:
    return 0

  while sub_idx < len(subs):
    gap = get_gap(subs, sub_idx)
    if gap >= config.split_gap_treshold:
      return sub_idx
    sub_idx += 1

  return len(subs)

def print_splits(subs, splits, config):
  # print("subs len: %d | %d" % (len(subs), subs[-1].end.ordinal))
  for i in range(1, len(splits)):
    # print("%d-%d" % (splits[i-1], splits[i]))
    print("interval %d: from %s to %s" % \
        (i, str(subs[splits[i-1]].start), str(subs[splits[i]-1].end)))

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
    new_fn = config.output if config.output else 'fixed.' + config.fn
    try:
      os.remove(new_fn)
    except OSError, e:
      pass
    subs.save(new_fn)
    final_name = new_fn

  logging.info("Subs written to %s" % final_name)

CHECK_TYPES = ["nocheck", "check", "fix"]

class Config(object):

  def __init__(self):
    self.fn = None
    self.fr = None
    self.to = None
    self.gap = "nocheck"
    self.string_length = "nocheck"
    self.duration = "nocheck"
    self.crop = False
    self.output = None
    self.split = False
    self.inplace_save = False

    self.rw = False

    self.min_gap = [100, 140]
    self.min_duration = 1500
    self.max_chars_per_sec = 28 # 1.5 sec for 42 chars
    self.max_string_length = 70
    self.split_interval = 5 * 60 * 1000 # 5 min
    self.split_gap_treshold = 750

  def from_args(self, argv):
    try:
      opts, args = getopt.getopt(argv, "", [
        "from=", "to=",
        "gap=", "string-length=",
        "duration=",
        "output=", "inplace", "crop",
        "split"
      ])
    except getopt.GetoptError, e:
      print(e)
      self.usage()

    # print("got args", opts, args)
    for opt, arg in opts:
      if opt == "--from":
        self.fr = arg
      elif opt == "--to":
        self.to = arg
      elif opt == "--gap":
        if arg in CHECK_TYPES:
          self.gap = arg
        else:
          self.bad_arg(opt, arg, CHECK_TYPES)
          self.usage()
      elif opt == "--string-length":
        if arg in CHECK_TYPES:
          self.string_length = arg
        else:
          self.bad_arg(opt, arg, CHECK_TYPES)
          self.usage()
      elif opt == "--duration":
        if arg in CHECK_TYPES:
          self.duration = arg
        else:
          self.bad_arg(opt, arg, CHECK_TYPES)
          self.usage()
      elif opt == "--output":
        self.output = arg
      elif opt == "--inplace":
        self.inplace_save = True
      elif opt == "--crop":
        self.crop = True
      elif opt == "--split":
        self.split = True

    if len(args) == 1:
      self.fn = args[0]
    elif len(args) == 0:
      print("subtitle filename not given")
      self.usage()
    else:
      print("too many arguments (expected one filename)")
      self.usage()

    self.consistency_check()

    # ops = True
    # for arg in args:
    #   if arg.startswith('-') and ops:
    #     if arg == '--':
    #       ops = False
    #       continue
    #     for opt in arg[1:]:
    #       print("got opt", opt)
    #       if opt == 'g':
    #         self.gap_check = True
    #       elif opt == 's':
    #         self.short_check = True
    #       elif opt == 'l':
    #         self.long_check = True
    #       elif opt == 'i':
    #         self.inplace_save = True
    #       else:
    #         logging.warning("Unrecognized option %s" % opt)
    #   elif self.fn == None:
    #     self.fn = arg
    #   elif self.new_fn == None:
    #     self.new_fn = arg
    #   else:
    #     logging.warning("Too many arguments")

    # if self.fn == None:
    #   self.usage()
  def compute_beg_end(self, subs):
    if self.fr == None:
      self.beg = 0
    else:
      ms = pysrt.SubRipTime.from_string(self.fr).ordinal
      sub_idx = bsrch(subs, ms)

      if sub_idx == len(subs):
        print("bad start time -- no subtitles after it")
        sys.exit(-1)

      if subs[sub_idx].start.ordinal != ms:
        print("could not match start time. nearest: %s" % str(subs[sub_idx].start))
      self.beg = sub_idx

    if self.to == None:
      self.end = len(subs)
    else:
      ms = pysrt.SubRipTime.from_string(self.to).ordinal
      sub_idx = bsrch(subs, ms) - 1

      if sub_idx == 0:
        print("bad end time -- no subs before it")
        sys.exit(-1)

      if sub_idx == len(subs):
        sub_idx -= 1

      if subs[sub_idx].end.ordinal != ms:
        print("could not match end time. nearest %s" % str(subs[sub_idx].end))

      self.end = sub_idx + 1 # one after the last

    print("sub idx %d %d" % (self.beg, self.end))

  def consistency_check(self):
    # TODO: Check from/to args
    if self.split:
      if self.gap != "nocheck" or self.duration != "nocheck" or \
          self.string_length != "nocheck" or self.crop or self.fr or self.to:
        print("%d %d %d %d %d %d" % (self.gap != "nocheck", self.duration != "nocheck", \
            self.string_length != "nockeck", bool(self.crop), bool(self.fr), bool(self.to)))
        print("if split is given it should be the only option")
        self.usage();

    if self.gap == "fix" or self.duration == "fix" or self.crop:
      self.rw = True
    else:
      self.rw = False

  def bad_arg(self, opt, arg, possible_args):
    print("%s does not accept argument %s. Possible values are %s" % (
      opt, arg, ", ".join(possible_args)))

  def usage(self):
    print("""
timeshift [OPTIONS] filename
          --split
              show split locations
          --from HH:MM:SS,DDD
              Specify the begining of the interval to be examined.
              Must match exactly the start time of a subtitle.
          --to HH:MM:SS,DDD
              Specify the end of the interval to be examined.
              Must match exactly the end time of a subtitle.
          --gap nocheck|check|fix
          --string-length nocheck|check
          --duration nocheck|check|fix
          --inplace
              Overwrite original file.
          --output filename
          --crop"
              Save only the from-to interval.
""")

    sys.exit(-1)

config = Config()
# print("%s" % (sys.argv[1:]))
config.from_args(sys.argv[1:])
# sys.exit(0)

subs = load_subs(config.fn)
if config.split:
  splits = []
  for s in range(0, subs[-1].end.ordinal, config.split_interval):
    sub_idx = find_big_gap(subs, s, config)
    splits.append(sub_idx)

  assert(len(splits) > 0)
  if splits[-1] != len(subs):
    splits.append(len(subs))

  print_splits(subs, splits, config)
else:
  config.compute_beg_end(subs)
  slen_res = check_string_length(subs, config)
  print("string length:");
  for m in slen_res:
    print(m)
  # print(slen_res)
  dur_res = check_duration(subs, config)
  print("duration:")
  for m in dur_res:
    print(m)
  # print(dur_res)
  gap_res = check_gap(subs, config)
  print("gaps:")
  for m in gap_res:
    print(m)
  # print(gap_res)

  if config.rw:
    if config.crop:
      subs = pysrt.SubRipFile(items = subs[config.beg:config.end])
    save_subs(subs)

  # print("Summary:")
  # for k in dir(summary):
  #   if k.startswith('__'):
  #     continue
  #   print("%s: %s" % (k, summary.__getattribute__(k)))
# ensure_gap(subs)
# check_short(subs)
# check_long(subs)



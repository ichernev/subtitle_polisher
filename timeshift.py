#!/bin/env python

import pysrt
import logging
import sys  # argv
import os   # remove, rename
import getopt # parsing cmd line options

logging.basicConfig(level = logging.INFO)

def load_subs(filename):
  return pysrt.SubRipFile.open(filename)

TEXT_LONG = 1
TIMING_ISSUE = 2

INFO = 1
WARNING = 2
ERROR = 3
FIX = 1
NOFIX = 2

class SrtItemIssue(object):
  issue2str = {
      TEXT_LONG: lambda data: "is too long (%d chars)" % data['length'],
      TIMING_ISSUE:
          lambda data: "has bad duration (or gap) (%d ms, %d chars/s)" % \
          (data['duration'], data['charsPerSec'])
  }

  def fixEnd(self):
    self.srtitem.end = pysrt.SubRipTime(milliseconds = self.data['newEnd'])

  issue2fix = {
      TIMING_ISSUE: fixEnd,
  }

  level2str = {
      INFO: 'INFO',
      WARNING: 'WARNING',
      ERROR: 'ERROR',
  }

  fix2str = {
      FIX: 'FIX',
      NOFIX: 'NOFIX',
  }

  def __init__(self, srtitem, issueId, level, fix, **kwargs):
    self.srtitem = srtitem
    self.issueId = issueId
    self.level = level
    self.fix = fix

    self.data = kwargs

  def __str__(self):
    return "[%s]<%s> Subtitle from %s to %s %s" % (self.level2str[self.level], \
        self.fix2str[self.fix],  self.srtitem.start, self.srtitem.end, \
        self.issue2str[self.issueId](self.data))

  def tryfix(self):
    if self.fix == FIX:
      try:
        self.issue2fix[self.issueId](self)
      except Exception as e:
        print(e)
        print(self.data)

def check_text_length(subs, config):
  res = []

  for i in range(config.beg, config.end):
    slen = len(subs[i].text)
    if slen > config.max_string_length[1]:
      res.append(SrtItemIssue(subs[i], TEXT_LONG, ERROR, NOFIX, length = slen))
    elif slen > config.max_string_length[0]:
      res.append(SrtItemIssue(subs[i], TEXT_LONG, WARNING, NOFIX, length = slen))

  return res

def analyze_timing(subs, config):
  res = []
  
  for i in range(config.beg, config.end):
    start = subs[i].start.ordinal
    end = subs[i].end.ordinal
    duration = end - start
    charsPerSec = len(subs[i].text) / (duration / 1000.0)
    maxEnd = subs[i + 1].start.ordinal if i + 1 < len(subs) \
        else end + 5 * 60 * 1000
    maxEnd = maxEnd - config.min_gap
    targetEnd = start + \
        max(config.min_duration, config.max_chars_per_sec * len(subs[i].text))

    data = { 'duration': duration, 'charsPerSec': charsPerSec }
    if maxEnd < start:
      level = ERROR
      fix = NOFIX
    elif targetEnd < maxEnd:
      level = INFO
      fix = FIX
      if end < targetEnd:
        data['newEnd'] = targetEnd
      elif end > maxEnd:
        data['newEnd'] = maxEnd
      else:
        level = None
    else:
      level = WARNING
      fix = FIX
      data['newEnd'] = maxEnd
    if level is not None: res.append(SrtItemIssue(subs[i], TIMING_ISSUE, level, fix, **data)) 

  return res

def bsrch(subs, time):
  if subs[-1].end.ordinal < time:
    return len(subs)

  l = -1
  r = len(subs)
  while l + 1 < r:
    m = (l + r) / 2
    if time < subs[m].end.ordinal:
      r = m
    else:
      l = m
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

def fixedFilename(fn):
  return os.path.join(os.path.dirname(fn), 'fixed.' + os.path.basename(fn))

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
    new_fn = config.output if config.output else fixedFilename(config.fn)
    try:
      os.remove(new_fn)
    except OSError, e:
      pass
    subs.save(new_fn)
    final_name = new_fn

  logging.info("Subs written to %s" % final_name)

class Config(object):

  def __init__(self):
    self.fn = None
    self.fr = None
    self.to = None
    self.text_length = None
    self.timing = None
    self.crop = False
    self.output = None
    self.split = False
    self.inplace_save = False

    self.rw = False

    self.min_gap = 150
    self.min_duration = 1500
    self.max_chars_per_sec = 28 # 1.5 sec for 42 chars
    self.max_string_length = [70, 80]
    self.split_interval = 5 * 60 * 1000 # 5 min
    self.split_gap_treshold = 750

  def from_args(self, argv):
    try:
      opts, args = getopt.getopt(argv, '', [
        'from=', 'to=',
        # 'gap=', 'string-length=', 'duration=',
        'check-text-length', 'check-timing', 'fix-timing',
        'output=', 'inplace', 'crop',
        'split',
      ])
    except getopt.GetoptError, e:
      print(e)
      self.usage()

    # print("got args", opts, args)
    for opt, arg in opts:
      if opt == '--from':
        self.fr = arg
      elif opt == '--to':
        self.to = arg
      elif opt == '--check-timing':
        self.timing = 'check'
      elif opt == '--fix-timing':
        self.timing = 'fix'
      elif opt == '--check-text-length':
        self.text_length = 'check'
      elif opt == '--output':
        self.output = arg
      elif opt == '--inplace':
        self.inplace_save = True
      elif opt == '--crop':
        self.crop = True
      elif opt == '--split':
        self.split = True

    if len(args) == 1:
      self.fn = args[0]
    elif len(args) == 0:
      print("subtitle filename not given\n")
      self.usage()
    else:
      print("too many arguments (expected one filename)")
      self.usage()

    self.consistency_check()

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

  def consistency_check(self):
    # TODO: Check from/to args
    if self.split:
      if self.text_length is not None or self.timing is not None or \
          self.crop or self.fr or self.to:
        print("If split is given it should be the only option.")
        self.usage();

    if self.timing == 'fix' or self.crop:
      self.rw = True
    else:
      self.rw = False

  def bad_arg(self, opt, arg, possible_args):
    print("%s does not accept argument %s. Possible values are %s" % (
      opt, arg, ", ".join(possible_args)))

  def usage(self):
    print("""timeshift [OPTIONS] filename
          --split
              show split locations
          --from HH:MM:SS,DDD
              Specify the begining of the interval to be examined.
              Must match exactly the start time of a subtitle.
          --to HH:MM:SS,DDD
              Specify the end of the interval to be examined.
              Must match exactly the end time of a subtitle.
          --check-text-length
          --check-timing
          --fix-timing
          --inplace
              Overwrite original file.
          --output filename
          --crop
              Save only the from-to interval.""")

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
  if config.text_length == 'check':
    for issue in check_text_length(subs, config):
      print(issue)
  if config.timing is not None:
    timing_issues = analyze_timing(subs, config)
    if config.timing == 'fix':
      for issue in timing_issues:
        issue.tryfix()
        if issue.level >= WARNING:
          print(issue)
    else:
      for issue in timing_issues:
        print(issue)

  if config.rw:
    if config.crop:
      subs = pysrt.SubRipFile(items = subs[config.beg:config.end])
    save_subs(subs)

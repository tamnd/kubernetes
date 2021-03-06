#!/usr/bin/env python

# Copyright 2015 The Kubernetes Authors All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

import json
import mmap
import os
import re
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("filenames", help="list of files to check, all files if unspecified", nargs='*')
parser.add_argument("-e", "--skip-exceptions", help="ignore hack/verify-flags/exceptions.txt and print all output", action="store_true")
args = parser.parse_args()


dashRE = re.compile('[-_]')

# Cargo culted from http://stackoverflow.com/questions/898669/how-can-i-detect-if-a-file-is-binary-non-text-in-python
def is_binary(pathname):
    """Return true if the given filename is binary.
    @raise EnvironmentError: if the file does not exist or cannot be accessed.
    @attention: found @ http://bytes.com/topic/python/answers/21222-determine-file-type-binary-text on 6/08/2010
    @author: Trent Mick <TrentM@ActiveState.com>
    @author: Jorge Orpinel <jorge@orpinel.com>"""
    try:
        f = open(pathname, 'r')
        CHUNKSIZE = 1024
        while 1:
            chunk = f.read(CHUNKSIZE)
            if '\0' in chunk: # found null byte
                return True
            if len(chunk) < CHUNKSIZE:
                break # done
    except:
        return True
    finally:
        f.close()
    return False

def get_all_files(rootdir):
    all_files = []
    for root, dirs, files in os.walk(rootdir):
        # don't visit certain dirs
        if 'Godeps' in dirs:
            dirs.remove('Godeps')
        if 'third_party' in dirs:
            dirs.remove('third_party')
        if '.git' in dirs:
            dirs.remove('.git')
        if 'exceptions.txt' in files:
            files.remove('exceptions.txt')
        if 'known-flags.txt' in files:
            files.remove('known-flags.txt')

        for name in files:
            if name.endswith(".svg"):
                continue
            if name.endswith(".gliffy"):
                continue
            pathname = os.path.join(root, name)
            if is_binary(pathname):
                continue
            all_files.append(pathname)
    return all_files

def normalize_files(rootdir, files):
    newfiles = []
    a = ['Godeps', 'third_party', 'exceptions.txt', 'known-flags.txt']
    for f in files:
        if any(x in f for x in a):
            continue
        if f.endswith(".svg"):
            continue
        if f.endswith(".gliffy"):
            continue
        newfiles.append(f)
    for i, f in enumerate(newfiles):
        if not os.path.isabs(f):
            newfiles[i] = os.path.join(rootdir, f)
    return newfiles

def line_has_bad_flag(line, flagre):
    m  = flagre.search(line)
    if not m:
        return False
    if "_" in m.group(0):
        return True
    return False

# The list of files might not be the whole repo. If someone only changed a
# couple of files we don't want to run all of the golang files looking for
# flags. Instead load the list of flags from hack/verify-flags/known-flags.txt
# If running the golang files finds a new flag not in that file, return an
# error and tell the user to add the flag to the flag list.
def get_flags(rootdir, files):
    # use a set for uniqueness
    flags = set()

    # preload the 'known' flags
    pathname = os.path.join(rootdir, "hack/verify-flags/known-flags.txt")
    f = open(pathname, 'r')
    for line in f.read().splitlines():
        flags.add(line)
    f.close()

    regexs = [ re.compile('Var[P]?\([^,]*, "([^"]*)"'),
               re.compile('.String[P]?\("([^"]*)",[^,]+,[^)]+\)'),
               re.compile('.Int[P]?\("([^"]*)",[^,]+,[^)]+\)'),
               re.compile('.Bool[P]?\("([^"]*)",[^,]+,[^)]+\)'),
               re.compile('.Duration[P]?\("([^"]*)",[^,]+,[^)]+\)'),
               re.compile('.StringSlice[P]?\("([^"]*)",[^,]+,[^)]+\)') ]

    new_flags = set()
    # walk all the files looking for any flags being declared
    for pathname in files:
        if not pathname.endswith(".go"):
            continue
        f = open(pathname, 'r')
        data = f.read()
        f.close()
        matches = []
        for regex in regexs:
            matches = matches + regex.findall(data)
        for flag in matches:
            # if the flag doesn't have a - or _ it is not interesting
            if not dashRE.search(flag):
                continue
            if flag not in flags:
                new_flags.add(flag)
    if len(new_flags) != 0:
        print("Found flags in golang files not in the list of known flags. Please add these to hack/verify-flags/known-flags.txt")
        print("%s" % "\n".join(new_flags))
        sys.exit(1)
    return list(flags)

def flags_to_re(flags):
    """turn the list of all flags we found into a regex find both - and _ version"""
    flagREs = []
    for flag in flags:
        # turn all flag names into regexs which will find both types
        newre = dashRE.sub('[-_]', flag)
        flagREs.append(newre)
    # turn that list of regex strings into a single large RE
    flagRE = "|".join(flagREs)
    flagRE = re.compile(flagRE)
    return flagRE

def load_exceptions(rootdir):
    exceptions = set()
    if args.skip_exceptions:
        return exceptions
    exception_filename = os.path.join(rootdir, "hack/verify-flags/exceptions.txt")
    exception_file = open(exception_filename, 'r')
    for exception in exception_file.read().splitlines():
        out = exception.split(":", 1)
        if len(out) != 2:
            printf("Invalid line in exceptions file: %s" % exception)
            continue
        filename = out[0]
        line = out[1]
        exceptions.add((filename, line))
    return exceptions

def main():
    rootdir = os.path.dirname(__file__) + "/../"
    rootdir = os.path.abspath(rootdir)

    exceptions = load_exceptions(rootdir)

    if len(args.filenames) > 0:
        files = args.filenames
    else:
        files = get_all_files(rootdir)
    files = normalize_files(rootdir, files)

    flags = get_flags(rootdir, files)
    flagRE = flags_to_re(flags)

    bad_lines = []
    # walk all the file looking for any flag that was declared and now has an _
    for pathname in files:
        relname = os.path.relpath(pathname, rootdir)
        f = open(pathname, 'r')
        for line in f.read().splitlines():
            if line_has_bad_flag(line, flagRE):
                if (relname, line) not in exceptions:
                    bad_lines.append((relname, line))
        f.close()

    if len(bad_lines) != 0:
        if not args.skip_exceptions:
            print("Found illegal 'flag' usage. If this is a false positive add the following line(s) to hack/verify-flags/exceptions.txt:")
        for (relname, line) in bad_lines:
            print("%s:%s" % (relname, line))

if __name__ == "__main__":
  sys.exit(main())

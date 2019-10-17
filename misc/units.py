#!/usr/bin/env python3

#
# units.py - Units test harness for ctags
#
# Copyright (C) 2019 Ken Takata
# (Based on "units" written by Masatake YAMATO.)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

#
# Python 3.5 or later is required.
# On Windows, this should be executed by Cygwin/MSYS2 python3.
# Windows native versions of python don't work for now.
#

import time     # for debugging
import argparse
import filecmp
import glob
import io
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading

#
# Global Parameters
#
SHELL = '/bin/sh'
CTAGS = './ctags'
READTAGS = './readtags'
WITH_TIMEOUT = 0
WITH_VALGRIND = False
COLORIZED_OUTPUT = True
CATEGORIES = []
UNITS = []
LANGUAGES = []
PRETENSE_OPTS = ''
RUN_SHRINK = False
SHOW_DIFF_OUTPUT = False
NUM_WORKER_THREADS = 4

#
# Internal variables and constants
#
_FEATURE_LIST = []
_PREPERE_ENV = ''
_DEFAULT_CATEGORY = 'ROOT'
_TIMEOUT_EXIT = 124
_VG_TIMEOUT_FACTOR = 10
_VALGRIND_EXIT = 58
_STDERR_OUTPUT_NAME = 'STDERR.tmp'
_DIFF_OUTPUT_NAME = 'DIFF.tmp'

#
# Results
#
L_PASSED = []
L_FIXED = []
L_FAILED_BY_STATUS = []
L_FAILED_BY_DIFF = []
L_SKIPPED_BY_FEATURES = []
L_SKIPPED_BY_LANGUAGES = []
L_SKIPPED_BY_ILOOP = []
L_KNOWN_BUGS = []
L_FAILED_BY_TIMEED_OUT = []
L_BROKEN_ARGS_CTAGS = []
L_VALGRIND = []
TMAIN_STATUS = True
TMAIN_FAILED = []

def remove_prefix(string, prefix):
    if string.startswith(prefix):
        return string[len(prefix):]
    else:
        return string

def is_cygwin():
    system = platform.system()
    return system.startswith('CYGWIN_NT') or system.startswith('MINGW32_NT')

def isabs(path):
    if is_cygwin():
        import ntpath
        if ntpath.isabs(path):
            return True
    return os.path.isabs(path)

def line(*args, file=sys.stdout):
    if len(args) > 0:
        ch = args[0]
    else:
        ch = '-'
    print(ch * 60, file=file)

def clean_tcase(d, bundles):
    if os.path.isdir(d):
        if os.path.isfile(bundles):
            with open(bundles, 'r') as f:
                for l in f:
                    fn = l.replace("\n", '')
                    if os.path.isdir(fn):
                        shutil.rmtree(fn)
                    elif os.path.isfile(fn):
                        os.remove(fn)
            os.remove(bundles)
        for fn in glob.glob(d + '/*.tmp') + glob.glob(d + '/*.TMP'):
            os.remove(fn)

def check_availability(cmd):
    if not shutil.which(cmd):
        error_exit(1, cmd + ' command is not available')

def check_units(name, category):
    if len(UNITS) == 0:
        return True

    for u in UNITS:
        ret = re.match(r'(.+)/(.+)', u)
        if ret:
            if ret.group(1, 2) == (category, name):
                return True
        elif u == name:
            return True
    return False

def init_features():
    global _FEATURE_LIST
    ret = subprocess.run([CTAGS + ' --quiet --options=NONE --list-features --with-list=no'],
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _FEATURE_LIST = re.sub(r'(?m)^([^ ]+).*$', r'\1',
            ret.stdout.decode('utf-8')).splitlines()

def check_features(feature, ffile):
    features = []
    if feature:
        features = [feature]
    elif os.path.isfile(ffile):
        with open(ffile, 'r') as f:
            features = f.read().splitlines()

    for expected in features:
        if expected == '':
            continue
        found = False
        found_unexpectedly = False
        if expected[0] == '!':
            if expected[1:] in _FEATURE_LIST:
                found_unexpectedly = True
        else:
            if expected in _FEATURE_LIST:
                found = True
        if found_unexpectedly:
            return (False, expected)
        elif not found:
            return (False, expected)
    return (True, '')

def check_languages(cmdline, lfile):
    if not os.path.isfile(lfile):
        return (True, '')

    ret = subprocess.run([cmdline + ' --list-languages'],
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    langs = ret.stdout.decode('utf-8').splitlines()

    with open(lfile, 'r') as f:
        for expected in f.read().splitlines():
            found = False
            if expected in langs:
                found = True
            if not found:
                return (False, expected)
    return (True, '')

def decorate(decorator, msg, colorized):
    if decorator == 'red':
        num = '31'
    elif decorator == 'green':
        num = '32'
    elif decorator == 'yellow':
        num = '33'
    else:
        print('INTERNAL ERROR: wrong run_result function', file=sys.stderr)
        sys.exit(1)

    if colorized:
        return "\x1b[" + num + 'm' + msg + "\x1b[m"
    else:
        return msg

def run_result(result_type, msg, output, *args, file=sys.stdout):
    func_dict = {
            'skip': run_result_skip,
            'error': run_result_error,
            'ok': run_result_ok,
            'known_error': run_result_known_error,
            }

    func_dict[result_type](msg, file, COLORIZED_OUTPUT, *args)
    file.flush()
    if output:
        with open(output, 'w') as f:
            func_dict[result_type](msg, f, False, *args)

def run_result_skip(msg, f, colorized, *args):
    if len(args) > 0:
        print(msg + decorate('yellow', 'skipped', colorized) +
                ' (' + args[0] + ')', file=f)
    else:
        print(msg + decorate('yellow', 'skipped', colorized), file=f)

def run_result_error(msg, f, colorized, *args):
    if len(args) > 0:
        print(msg + decorate('red', 'failed', colorized) +
                ' (' + args[0] + ')', file=f)
    else:
        print(msg + decorate('red', 'failed', colorized), file=f)

def run_result_ok(msg, f, colorized, *args):
    if len(args) > 0:
        print(msg + decorate('green', 'passed', colorized) +
                ' (' + args[0] + ')', file=f)
    else:
        print(msg + decorate('green', 'passed', colorized), file=f)

def run_result_known_error(msg, f, colorized, *args):
    print(msg + decorate('yellow', 'failed', colorized) +
            ' (KNOWN bug)', file=f)

def run_shrink(cmdline_template, finput, foutput, lang):
    # TODO
    pass

def basename_filter(internal, output_type):
    filters = {
            'ctags': '\'s%\(^[^\t]\{1,\}\t\)\(/\{0,1\}\([^/\t]\{1,\}/\)*\)%\\1%\'',
            'etags': '\'s%.*\/\([[:print:]]\{1,\}\),\([0-9]\{1,\}$\)%\\1,\\2%\'',
            'xref': '\'s%\(.*[[:digit:]]\{1,\} \)\([^ ]\{1,\}[^ ]\{1,\}\)/\([^ ].\{1,\}.\{1,\}$\)%\\1\\3%\'',
            'json': '\'s%\("path": \)"[^"]\{1,\}/\([^/"]\{1,\}\)"%\\1"\\2"%\'',
            }
    filters_internal = {
            'ctags': (r'(^[^\t]+\t)(/?([^/\t]+/)*)', r'\1'),
            'etags': (r'.*/(\S+),([0-9]+$)', r'\1,\2'),
            'xref': (r'(.*\d+ )([^ ]+[^ ]+)/([^ ].+.+$)', r'\1\3'),
            'json': (r'("path": )"[^"]+/([^/"]+)"', r'\1"\2"'),
            }
    if internal:
        return filters_internal[output_type]
    else:
        return 'sed -e ' + filters[output_type]

def run_record_cmdline(cmdline, ffilter, ocmdline, output_type):
    with open(ocmdline, 'w') as f:
        print("%s\n%s \\\n| %s \\\n| %s\n" % (
            _PREPERE_ENV, cmdline,
            basename_filter(False, output_type),
            ffilter), file=f)

def prepare_bundles(frm, to, obundles):
    for src in glob.glob(frm + '/*'):
        fn = os.path.basename(src)
        if fn.startswith('input.'):
            continue
        elif fn.startswith('expected.tags'):
            continue
        elif fn.startswith('README'):
            continue
        elif fn in ['features', 'languages', 'filters']:
            continue
        elif fn == 'args.ctags':
            continue
        else:
            dist = to + '/' + fn
            if os.path.isdir(src):
                shutil.copytree(src, dist)
            else:
                shutil.copy(src, dist)
            with open(obundles, 'a') as f:
                print(dist, file=f)

def anon_normalize_sub(internal, ctags, input_actual, *args):
    # TODO: "Units" should not be hardcoded.
    input_expected = './Units' + re.sub(r'^.*?/Units', r'', input_actual, 1)

    ret = subprocess.run([CTAGS + ' --quiet --options=NONE --_anonhash="' + input_actual + '"'],
            shell=True, stdout=subprocess.PIPE)
    actual = ret.stdout.decode('utf-8').splitlines()[0]
    ret = subprocess.run([CTAGS + ' --quiet --options=NONE --_anonhash="' + input_expected + '"'],
            shell=True, stdout=subprocess.PIPE)
    expected = ret.stdout.decode('utf-8').splitlines()[0]

    if internal:
        rettup = (actual, expected)
        if len(args) > 0:
            return [rettup] + anon_normalize_sub(internal, ctags, *args)
        else:
            return [rettup]
    else:
        retstr = ' -e s/' + actual + '/' + expected + '/g'
        if len(args) > 0:
            return retstr + anon_normalize_sub(internal, ctags, *args)
        else:
            return retstr

def is_anon_normalize_needed(rawout):
    with open(rawout, 'r', errors='ignore') as f:
        if re.search(r'[0-9a-f]{8}', f.read()):
            return True
    return False

def anon_normalize(internal, rawout, ctags, input_actual, *args):
    if is_anon_normalize_needed(rawout):
        return anon_normalize_sub(internal, ctags, input_actual, *args)
    else:
        if internal:
            return ()
        else:
            return ''

def run_filter(finput, foutput, base_filter, anon_filters):
    pat1 = [re.compile(base_filter[0]), base_filter[1]]
    pat2 = [(re.compile(p[0]), p[1]) for p in anon_filters]
    with open(finput, 'r', errors='surrogateescape') as fin, \
            open(foutput, 'w', errors='surrogateescape', newline='\n') as fout:
        for l in fin:
            l = pat1[0].sub(pat1[1], l, 1)
            for p in pat2:
                l = p[0].sub(p[1], l)
            print(l, end='', file=fout)

def run_tcase(finput, t, name, tclass, category, build_t, extra_inputs):
    global L_PASSED
    global L_FIXED
    global L_FAILED_BY_STATUS
    global L_FAILED_BY_DIFF
    global L_SKIPPED_BY_FEATURES
    global L_SKIPPED_BY_LANGUAGES
    global L_SKIPPED_BY_ILOOP
    global L_KNOWN_BUGS
    global L_FAILED_BY_TIMEED_OUT
    global L_BROKEN_ARGS_CTAGS
    global L_VALGRIND

    o = build_t

    fargs = t + '/args.ctags'
    ffeatures = t + '/features'
    flanguages = t + '/languages'
    ffilter = t + '/filter'

    fexpected = t + '/expected.tags'
    output_type = 'ctags'
    output_label = ''
    output_tflag = ''
    output_feature = ''
    output_lang_extras = ''

    if os.path.isfile(fexpected):
        pass
    elif os.path.isfile(t + '/expected.tags-e'):
        fexpected = t + '/expected.tags-e'
        output_type = 'etags'
        output_label = '/' + output_type
        output_tflag = '-e --tag-relative=no'
    elif os.path.isfile(t + '/expected.tags-x'):
        fexpected = t + '/expected.tags-x'
        output_type = 'xref'
        output_label = '/' + output_type
        output_tflag = '-x'
    elif os.path.isfile(t + '/expected.tags-json'):
        fexpected = t + '/expected.tags-json'
        output_type = 'json'
        output_label = '/' + output_type
        output_tflag = '--output-format=json'
        output_feature = 'json'

    if len(extra_inputs) > 0:
        output_lang_extras = ' (multi inputs)'

    if not shutil.which(ffilter):
        ffilter = 'cat'

    ostderr = o + '/' + _STDERR_OUTPUT_NAME
    orawout = o + '/RAWOUT.tmp'
    ofiltered = o + '/FILTERED.tmp'
    odiff = o + '/' + _DIFF_OUTPUT_NAME
    ocmdline = o + '/CMDLINE.tmp'
    ovalgrind = o + '/VALGRIND.tmp'
    oresult = o + '/RESULT.tmp'
    oshrink_template = o + '/SHRINK-%s.tmp'
    obundles = o + '/BUNDLES'

    broken_args_ctags = False

    #
    # Filtered by UNIT
    #
    if not check_units(name, category):
        return False

    #
    # Build cmdline
    #
    cmdline = CTAGS + ' --verbose --options=NONE ' + PRETENSE_OPTS + ' --optlib-dir=+' + t + '/optlib -o -'
    if os.path.isfile(fargs):
        cmdline += ' --options=' + fargs
        ret = subprocess.run([cmdline + ' --_force-quit=0'],
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ret.returncode != 0:
            broken_args_ctags = True

    #
    # Filtered by LANGUAGES
    #
    start = time.time()
    ret = subprocess.run([cmdline + ' --print-language "' + finput + '"'],
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    #print('lang time: %f' % (time.time() - start))
    guessed_lang = re.sub(r'^.*: ', r'',
            ret.stdout.decode('utf-8').replace("\r\n", "\n").replace("\n", ''))
    oshrink = oshrink_template % (guessed_lang.replace('/', '-'))

    clean_tcase(o, obundles)
    os.makedirs(o, exist_ok=True)
    if os.path.realpath(o) != os.path.realpath(t):
        prepare_bundles(t, o, obundles)


    msg = '%-59s ' % ('Testing ' + name + ' as ' + guessed_lang + output_lang_extras + output_label)

    (tmp, feat) = check_features(output_feature, ffeatures)
    if not tmp:
        L_SKIPPED_BY_FEATURES += [category + '/' + name]
        if feat.startswith('!'):
            run_result('skip', msg, oresult, 'unwanted feature "' + feat[1:] + '" is available')
        else:
            run_result('skip', msg, oresult, 'required feature "' + feat + '" is not available')
        return False
    (tmp, lang) = check_languages(cmdline, flanguages)
    if not tmp:
        L_SKIPPED_BY_LANGUAGES += [category + '/' + name]
        run_result('skip', msg, oresult, 'required language parser "' + lang + '" is not available')
        return False
    if WITH_TIMEOUT == 0 and tclass == 'i':
        L_SKIPPED_BY_ILOOP += [category + '/' + name]
        run_result('skip', msg, oresult, 'may cause an infinite loop')
        return False
    if broken_args_ctags:
        L_BROKEN_ARGS_CTAGS += [category + '/' + name]
        run_result('error', msg, None, 'broken args.ctags?')
        return False

    cmdline_template = cmdline + ' --language-force=' + guessed_lang + ' %s > /dev/null 2>&1'
    cmdline += ' ' + output_tflag + ' ' + finput
    if len(extra_inputs) > 0:
        cmdline += ' "' + '" "'.join(extra_inputs) + '"'

    timeout_value = WITH_TIMEOUT
    if WITH_VALGRIND:
        cmdline = 'valgrind --leak-check=full --error-exitcode=' + str(_VALGRIND_EXIT) + ' --log-file=' + ovalgrind + ' ' + cmdline
        timeout_value *= _VG_TIMEOUT_FACTOR
    if timeout_value == 0:
        timeout_value = None

    start = time.time()
    try:
        ret = subprocess.run([cmdline + ' 2> ' + ostderr + ' > ' + orawout],
                shell=True, timeout=timeout_value)
        run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
    except subprocess.TimeoutExpired:
        L_FAILED_BY_TIMEED_OUT += [category + '/' + name]
        run_result('error', msg, oresult, 'TIMED OUT')
        run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
        if RUN_SHRINK and len(extra_inputs) == 0:
            run_shrink(cmdline_template, finput, oshrink, guessed_lang)
        return False
    #print('execute time: %f' % (time.time() - start))

    if ret.returncode != 0:
        if WITH_VALGRIND and ret.returncode == _VALGRIND_EXIT and \
                tclass != 'v':
            L_VALGRIND += [category + '/' + name]
            run_result('error', msg, oresult, 'valgrind-error')
            run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
            return False
        elif tclass == 'b':
            L_KNOWN_BUGS += [category + '/' + name]
            run_result('known_error', msg, oresult)
            run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
            if RUN_SHRINK and len(extra_inputs) == 0:
                run_shrink(cmdline_template, finput, oshrink, guessed_lang)
            return True
        else:
            L_FAILED_BY_STATUS += [category + '/' + name]
            run_result('error', msg, oresult, 'unexpected exit status: ' + str(ret.returncode))
            run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
            if RUN_SHRINK and len(extra_inputs) == 0:
                run_shrink(cmdline_template, finput, oshrink, guessed_lang)
            return False
    elif WITH_VALGRIND and tclass == 'v':
        L_FIXED += [category + '/' + name]

    if not os.path.isfile(fexpected):
        clean_tcase(o, obundles)
        if tclass == 'b':
            L_FIXED += [category + '/' + name]
        elif tclass == 'i':
            L_FIXED += [category + '/' + name]

        L_PASSED += [category + '/' + name]
        run_result('ok', msg, None, '"expected.tags*" not found')
        return True

    start = time.time()
    if ffilter != 'cat':
        # Use external filter
        filter_cmd = basename_filter(False, output_type) + \
                anon_normalize(False, orawout, CTAGS, finput, *extra_inputs) + \
                ' < ' + orawout
        filter_cmd += ' | ' + ffilter
        filter_cmd += ' > ' + '"' + ofiltered + '"'
        #print(filter_cmd)
        subprocess.run([filter_cmd], shell=True)
    else:
        # Use internal filter
        run_filter(orawout, ofiltered, basename_filter(True, output_type),
                anon_normalize(True, orawout, CTAGS, finput, *extra_inputs))
    #print('filter time: %f' % (time.time() - start))

    start = time.time()
    if filecmp.cmp(fexpected, ofiltered):
        ret.returncode = 0
    else:
        ret = subprocess.run(['diff -U 0 -I \'^!_TAG\' --strip-trailing-cr "' + fexpected + '" "' + ofiltered + '" > "' + odiff + '"'],
                shell=True)
    #print('diff time: %f' % (time.time() - start))

    if ret.returncode == 0:
        clean_tcase(o, obundles)
        if tclass == 'b':
            L_FIXED += [category + '/' + name]
        elif WITH_TIMEOUT != 0 and tclass == 'i':
            L_FIXED += [category + '/' + name]

        L_PASSED += [category + '/' + name]
        run_result('ok', msg, None)
        return True
    else:
        if tclass == 'b':
            L_KNOWN_BUGS += [category + '/' + name]
            run_result('known_error', msg, oresult)
            run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
            return True
        else:
            L_FAILED_BY_DIFF += [category + '/' + name]
            run_result('error', msg, oresult, 'unexpected output')
            run_record_cmdline(cmdline, ffilter, ocmdline, output_type)
            return False

def create_thread_queue(func):
    q = queue.Queue()
    threads = []
    for i in range(NUM_WORKER_THREADS):
        t = threading.Thread(target=worker, args=(func, q), daemon=True)
        t.start()
        threads.append(t)
    return (q, threads)

def worker(func, q):
    while True:
        item = q.get()
        if item is None:
            break
        try:
            func(*item)
        except:
            import traceback
            traceback.print_exc()
        q.task_done()

def join_workers(q, threads):
    # block until all tasks are done
    try:
        q.join()
    except KeyboardInterrupt:
        # empty the queue
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break
        # try to stop workers
        for i in range(NUM_WORKER_THREADS):
            q.put(None)
        for t in threads:
            t.join(timeout=2)
        # exit regardless that workers are stopped
        sys.exit(1)

    # stop workers
    for i in range(NUM_WORKER_THREADS):
        q.put(None)
    for t in threads:
        t.join()

def accepted_file(fname):
    # Ignore backup files
    return not fname.endswith('~')

def run_dir(category, base_dir, build_base_dir):
    #
    # Filtered by CATEGORIES
    #
    if len(CATEGORIES) > 0 and not category in CATEGORIES:
        return False

    print("\nCategory: " + category)
    line()

    (q, threads) = create_thread_queue(run_tcase)

    for finput in glob.glob(base_dir + '/*.[dbtiv]/input.*'):
        finput = finput.replace('\\', '/')  # for Windows
        if not accepted_file(finput):
            continue

        dname = os.path.dirname(finput)
        extra_inputs = sorted(map(lambda x: x.replace('\\', '/'), # for Windows
            filter(accepted_file,
                glob.glob(dname + '/input[-_][0-9].*') +
                glob.glob(dname + '/input[-_][0-9][-_]*.*')
            )))

        tcase_dir = dname
        build_tcase_dir = build_base_dir + remove_prefix(tcase_dir, base_dir)
        ret = re.match(r'^.*/(.*)\.([dbtiv])$', tcase_dir)
        (name, tclass) = ret.group(1, 2)
        q.put((finput, tcase_dir, name, tclass, category, build_tcase_dir, extra_inputs))

    join_workers(q, threads)

def run_show_diff_output(units_dir, t):
    print("\t", end='')
    line('.')
    for fn in glob.glob(units_dir + '/' + t + '.*/' + _DIFF_OUTPUT_NAME):
        with open(fn, 'r') as f:
            for l in f:
                print("\t" + l, end='')
    print()

def run_show_stderr_output(units_dir, t):
    print("\t", end='')
    line('.')
    for fn in glob.glob(units_dir + '/' + t + '.*/' + _STDERR_OUTPUT_NAME):
        with open(fn, 'r') as f:
            lines = f.readlines()
            for l in lines[-50:]:
                print("\t" + l, end='')
    print()

def run_summary(build_dir):
    print()
    print('Summary (see CMDLINE.tmp to reproduce without test harness)')
    line()

    fmt = '  %-40s%d'
    print(fmt % ('#passed:', len(L_PASSED)))

    print(fmt % ('#FIXED:', len(L_FIXED)))
    for t in L_FIXED:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    print(fmt % ('#FAILED (broken args.ctags?):', len(L_BROKEN_ARGS_CTAGS)))
    for t in L_BROKEN_ARGS_CTAGS:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    print(fmt % ('#FAILED (unexpected-exit-status):', len(L_FAILED_BY_STATUS)))
    for t in L_FAILED_BY_STATUS:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))
        if SHOW_DIFF_OUTPUT:
            run_show_stderr_output(build_dir, remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    print(fmt % ('#FAILED (unexpected-output):', len(L_FAILED_BY_DIFF)))
    for t in L_FAILED_BY_DIFF:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))
        if SHOW_DIFF_OUTPUT:
            run_show_stderr_output(build_dir, remove_prefix(t, _DEFAULT_CATEGORY + '/'))
            run_show_diff_output(build_dir, remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    if WITH_TIMEOUT != 0:
        print(fmt % ('#TIMED-OUT (' + str(WITH_TIMEOUT) + 's):', len(L_FAILED_BY_TIMEED_OUT)))
        for t in L_FAILED_BY_TIMEED_OUT:
            print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    print(fmt % ('#skipped (features):', len(L_SKIPPED_BY_FEATURES)))
    for t in L_SKIPPED_BY_FEATURES:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    print(fmt % ('#skipped (languages):', len(L_SKIPPED_BY_LANGUAGES)))
    for t in L_SKIPPED_BY_LANGUAGES:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    if WITH_TIMEOUT == 0:
        print(fmt % ('#skipped (infinite-loop):', len(L_SKIPPED_BY_ILOOP)))
        for t in L_SKIPPED_BY_ILOOP:
            print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    print(fmt % ('#known-bugs:', len(L_KNOWN_BUGS)))
    for t in L_KNOWN_BUGS:
        print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

    if WITH_VALGRIND:
        print(fmt % ('#valgrind-error:', len(L_VALGRIND)))
        for t in L_VALGRIND:
            print("\t" + remove_prefix(t, _DEFAULT_CATEGORY + '/'))

def make_pretense_map(arg):
    r = ''
    for p in arg.split(','):
        ret = re.match(r'(.*)/(.*)', p)
        if not ret:
            error_exit(1, 'wrong format of --_pretend option arg')

        (newlang, oldlang) = ret.group(1, 2)
        if newlang == '':
            error_exit(1, 'newlang part of --_pretend option arg is empty')
        if oldlang == '':
            error_exit(1, 'oldlang part of --_pretend option arg is empty')

        r += ' --_pretend-' + newlang + '=' + oldlang

    return r

def action_run(parser, action, *args):
    global CATEGORIES
    global CTAGS
    global UNITS
    global LANGUAGES
    global WITH_TIMEOUT
    global WITH_VALGRIND
    global COLORIZED_OUTPUT
    global RUN_SHRINK
    global SHOW_DIFF_OUTPUT
    global PRETENSE_OPTS
    global NUM_WORKER_THREADS

    parser.add_argument('--categories')
    parser.add_argument('--ctags')
    parser.add_argument('--units')
    parser.add_argument('--languages')
    parser.add_argument('--with-timeout', type=int, default=0)
    parser.add_argument('--with-valgrind', action='store_true', default=False)
    parser.add_argument('--colorized-output', choices=['yes', 'no'], default='yes')
    parser.add_argument('--run-shrink', action='store_true', default=False)
    parser.add_argument('--show-diff-output', action='store_true', default=False)
    parser.add_argument('--with-pretense-map')
    parser.add_argument('--threads', type=int, default=NUM_WORKER_THREADS)
    parser.add_argument('units_dir')
    parser.add_argument('build_dir', nargs='?', default='')

    res = parser.parse_args(args)
    if res.categories:
        CATEGORIES = [x if x == 'ROOT' or x.endswith('.r') else x + '.r'
                for x in res.categories.split(',')]
    if res.ctags:
        CTAGS = res.ctags
    if res.units:
        UNITS = res.units.split(',')
    if res.languages:
        LANGUAGES = res.languages.split(',')
    WITH_TIMEOUT = res.with_timeout
    WITH_VALGRIND = res.with_valgrind
    COLORIZED_OUTPUT = (res.colorized_output == 'yes')
    RUN_SHRINK = res.run_shrink
    SHOW_DIFF_OUTPUT = res.show_diff_output
    if res.with_pretense_map:
        PRETENSE_OPTS = make_pretense_map(res.with_pretense_map)
    NUM_WORKER_THREADS = res.threads
    if res.build_dir == '':
        res.build_dir = res.units_dir

    if WITH_VALGRIND:
        check_availability('valgrind')
    check_availability('diff')
    init_features()

    if isabs(res.build_dir):
        build_dir = res.build_dir
    else:
        build_dir = os.path.realpath(res.build_dir)

    category = _DEFAULT_CATEGORY
    if len(CATEGORIES) == 0 or (category in CATEGORIES):
        run_dir(category, res.units_dir, build_dir)

    for d in glob.glob(res.units_dir + '/*.r'):
        d = d.replace('\\', '/')    # for Windows
        if not os.path.isdir(d):
            continue
        category = os.path.basename(d)
        build_d = res.build_dir + '/' + category
        run_dir(category, d, build_d)

    run_summary(build_dir)

    if L_FAILED_BY_STATUS or L_FAILED_BY_DIFF or \
            L_FAILED_BY_TIMEED_OUT or L_BROKEN_ARGS_CTAGS:
        return 1
    else:
        return 0

def tmain_compare_result(build_topdir):
    for fn in glob.glob(build_topdir + '/*/*-diff.txt'):
        print(fn)
        print()
        with open(fn, 'r', errors='replace') as f:
            for l in f:
                print("\t" + l, end='')
        print()

    for fn in glob.glob(build_topdir + '/*/gdb-backtrace.txt'):
        with open(fn, 'r', errors='replace') as f:
            for l in f:
                print("\t" + l, end='')

def tmain_compare(subdir, build_subdir, aspect, file):
    msg = '%-59s ' % (aspect)
    generated = build_subdir + '/' + aspect + '-diff.txt'
    actual = build_subdir + '/' + aspect + '-actual.txt'
    expected = subdir + '/' + aspect + '-expected.txt'
    if os.path.isfile(actual) and os.path.isfile(expected) and \
            filecmp.cmp(actual, expected):
        run_result('ok', msg, None, file=file)
        return True
    else:
        ret = subprocess.run(['diff -U 0 --strip-trailing-cr "' +
                actual + '" "' + expected +
                '" > "' + generated + '" 2>&1'],
                shell=True)
        run_result('error', msg, None, 'diff: ' + generated, file=file)
        return False

def failed_git_marker(fn):
    if shutil.which('git'):
        ret = subprocess.run(['git ls-files -- "' + fn + '"'],
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ret.stdout == b'':
            return '<G>'
    return ''

def is_crashed(fn):
    with open(fn, 'r') as f:
        if 'core dump' in f.read():
            return True
    return False

def print_backtraces(ctags_exe, cores, fn):
    with open(fn, 'w') as f:
        for coref in cores:
            ret = subprocess.run(['gdb "' + ctags_exe + '" -c "' + coref + '" -ex where -batch'],
                shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(ret.stdout.decode('utf-8'), end='', file=f)

def tmain_sub(test_name, basedir, subdir, build_subdir):
    global TMAIN_STATUS
    global TMAIN_FAILED

    CODE_FOR_IGNORING_THIS_TMAIN_TEST = 77

    os.makedirs(build_subdir, exist_ok=True)

    for fn in glob.glob(build_subdir + '/*-actual.txt'):
        os.remove(fn)

    strbuf = io.StringIO()
    print("\nTesting " + test_name, file=strbuf)
    line('-', file=strbuf)

    if isabs(CTAGS):
        ctags_path = CTAGS
    else:
        ctags_path = os.path.join(basedir, CTAGS)

    if isabs(READTAGS):
        readtags_path = READTAGS
    else:
        readtags_path = os.path.join(basedir, READTAGS)

    ret = subprocess.run([SHELL + ' run.sh ' +
            ctags_path + ' ' +
            build_subdir + ' ' +
            readtags_path],
            cwd=subdir,
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    encoding = 'utf-8'
    try:
        stdout = ret.stdout.decode(encoding).replace("\r\n", "\n")
    except UnicodeError:
        encoding = 'iso-8859-1'
        stdout = ret.stdout.decode(encoding).replace("\r\n", "\n")
    stderr = ret.stderr.decode('utf-8').replace("\r\n", "\n")
    if os.path.basename(CTAGS) != 'ctags':
        # program name needs to be canonicalized
        stderr = re.sub('(?m)^' + os.path.basename(CTAGS) + ':', 'ctags:', stderr)

    if ret.returncode == CODE_FOR_IGNORING_THIS_TMAIN_TEST:
        run_result('skip', '', None, stdout.replace("\n", ''), file=strbuf)
        print(strbuf.getvalue(), end='')
        sys.stdout.flush()
        strbuf.close()
        return True

    with open(build_subdir + '/exit-actual.txt', 'w', newline='\n') as f:
        print(ret.returncode, file=f)
    with open(build_subdir + '/stdout-actual.txt', 'w', newline='\n', encoding=encoding) as f:
        print(stdout, end='', file=f)
    with open(build_subdir + '/stderr-actual.txt', 'w', newline='\n') as f:
        print(stderr, end='', file=f)

    if os.path.isfile(build_subdir + '/tags'):
        os.rename(build_subdir + '/tags', build_subdir + '/tags-actual.txt')

    for aspect in ['stdout', 'stderr', 'exit', 'tags']:
        expected_txt = subdir + '/' + aspect + '-expected.txt'
        actual_txt = build_subdir + '/' + aspect + '-actual.txt'
        if os.path.isfile(expected_txt):
            if tmain_compare(subdir, build_subdir, aspect, strbuf):
                os.remove(actual_txt)
            else:
                TMAIN_FAILED += [test_name + '/' + aspect + '-compare' +
                        failed_git_marker(expected_txt)]
                TMAIN_STATUS = False
                if aspect == 'stderr' and \
                        is_crashed(actual_txt) and \
                        shutil.which('gdb'):
                    print_backtraces(ctags_path,
                            glob.glob(build_subdir + '/core*'),
                            build_subdir + '/gdb-backtrace.txt')
        elif os.path.isfile(actual_txt):
            os.remove(actual_txt)

    print(strbuf.getvalue(), end='')
    sys.stdout.flush()
    strbuf.close()
    return True

def tmain_run(topdir, build_topdir, units):
    global TMAIN_STATUS

    TMAIN_STATUS = True

    (q, threads) = create_thread_queue(tmain_sub)

    basedir = os.getcwd()
    for subdir in glob.glob(topdir + '/*.d'):
        test_name = os.path.basename(subdir)[:-2]

        if len(units) > 0 and not test_name in units:
            continue

        build_subdir = build_topdir + '/' + os.path.basename(subdir)
        q.put((test_name, basedir, subdir, build_subdir))

    join_workers(q, threads)

    print()
    if not TMAIN_STATUS:
        print('Failed tests')
        line('=')
        for f in TMAIN_FAILED:
            print(re.sub('<G>', ' (not committed/cached yet)', f))
        print()

        if SHOW_DIFF_OUTPUT:
            print('Detail [compare]')
            line('-')
            tmain_compare_result(build_topdir)

    return TMAIN_STATUS

def action_tmain(parser, action, *args):
    global CTAGS
    global COLORIZED_OUTPUT
    global WITH_VALGRIND
    global SHOW_DIFF_OUTPUT
    global READTAGS
    global UNITS
    global NUM_WORKER_THREADS

    parser.add_argument('--ctags')
    parser.add_argument('--colorized-output', choices=['yes', 'no'], default='yes')
    parser.add_argument('--with-valgrind', action='store_true', default=False)
    parser.add_argument('--show-diff-output', action='store_true', default=False)
    parser.add_argument('--readtags')
    parser.add_argument('--units')
    parser.add_argument('--threads', type=int, default=NUM_WORKER_THREADS)
    parser.add_argument('tmain_dir')
    parser.add_argument('build_dir', nargs='?', default='')

    res = parser.parse_args(args)
    if res.ctags:
        CTAGS = res.ctags
    COLORIZED_OUTPUT = (res.colorized_output == 'yes')
    WITH_VALGRIND = res.with_valgrind
    SHOW_DIFF_OUTPUT = res.show_diff_output
    if res.readtags:
        READTAGS = res.readtags
    if res.units:
        UNITS = res.units.split(',')
    NUM_WORKER_THREADS = res.threads
    if res.build_dir == '':
        res.build_dir = res.tmain_dir

    #check_availability('awk')
    check_availability('diff')

    if isabs(res.build_dir):
        build_dir = res.build_dir
    else:
        build_dir = os.path.realpath(res.build_dir)

    ret = tmain_run(res.tmain_dir, build_dir, UNITS)
    if ret:
        return 0
    else:
        return 1

def action_help(parser, *args):
    parser.print_help()
    return 0

def prepare_environment():
    global _PREPERE_ENV

    os.environ['LC_ALL'] = 'C'
    os.environ['MSYS2_ARG_CONV_EXCL'] = '--regex-;--_scopesep'

    _PREPERE_ENV = """LC_ALL="C"; export LC_ALL
MSYS2_ARG_CONV_EXCL='--regex-;--_scopesep' export MSYS2_ARG_CONV_EXCL
"""

def main():
    prepare_environment()

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='action')
    cmdmap = {}
    cmdmap['run'] = [action_run, subparsers.add_parser('run', aliases=['units'])]
    cmdmap['units'] = cmdmap['run']
    cmdmap['tmain'] = [action_tmain, subparsers.add_parser('tmain')]
    subparsers.add_parser('help')
    cmdmap['help'] = [action_help, parser]

    if len(sys.argv) < 2:
        parser.print_help()
        sys.exit(1)

    res = parser.parse_args(sys.argv[1:2])
    (func, subparser) = cmdmap[res.action]
    sys.exit(func(subparser, *sys.argv[1:]))

if __name__ == '__main__':
    main()

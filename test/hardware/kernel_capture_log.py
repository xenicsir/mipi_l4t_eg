"""Read only new kernel records; preserve errors, sequence gaps and qualifications."""
import errno
import json
import os
import re
from pathlib import Path


def classify(message, priority):
    message = message.split('\n', 1)[0]  # /dev/kmsg may append device metadata.
    if re.search(r'callbacks suppressed|messages suppressed|printk.*dropped', message, re.I):
        return 'log_loss'
    if re.search(r'BUG:|Oops:|Kernel panic|WARNING: CPU:|soft lockup|hard LOCKUP|hung task|blocked for more than|use-after-free|KASAN:|IOMMU.*fault|smmu.*fault', message, re.I):
        return 'kernel_fault'
    if re.search(r'\b(?:corr_err|uncorr_err):', message):
        return 'capture_error'
    # This platform message occurs on normal Forecr bandwidth setup/teardown.
    # Retain it with an explicit classification, not as a capture failure.
    if re.search(r'\bbwmgr API not supported\s*$', message):
        return 'known_platform_message'
    if re.search(r'\b(?:vi[245]?|nvcsi|csi|camera|capture|rtcpu|rce|camrtc|dione\w*|ilumos|titan|microlynx|eg.ec.mipi)\b', message, re.I) and re.search(r'error|failed|failure|timeout|timed out|discard|overflow|underflow|CHANSEL_|CSIMUX_|VIFALC_', message, re.I):
        return 'camera_error'
    if priority <= 3:
        return 'kernel_error'
    return 'info'


def decode(record):
    head, message = record.decode(errors='replace').split(';', 1)
    fields = head.split(',')
    priority, sequence, usec = map(int, fields[:3])
    message = message.rstrip('\n')
    return dict(sequence=sequence, timestamp_us=usec, priority=priority & 7,
                message=message, category=classify(message, priority & 7))


def qualify(window, camera_name='', integrity=None, simultaneous=False):
    """Only the existing, observed FIRST-buffer Dione exception is eligible."""
    errors = window['errors']
    for row in errors:
        row.pop('qualification', None)
    eligible = (not simultaneous and camera_name.lower().startswith('dione')
                and integrity and integrity.get('startup_exception') and len(errors) == 1)
    if eligible and re.search(r'\bcorr_err:.*status 14, flags: 0, err_data 0x0*40\b', errors[0]['message']):
        errors[0]['qualification'] = 'Existing Dione first ERROR-buffer exception; not proof of firmware origin'
    window['clean'] = window['complete'] and not errors
    window['unqualified_messages'] = sum(not row.get('qualification') for row in errors)
    window['affects_test_result'] = False
    return window


class KernelCaptureLog:
    def __init__(self, output):
        self.output = Path(output)
        self.windows = []
        self.last_sequence = None
        self.fd = None
        self.failure = None
        self.fatal = False
        try:
            self.fd = os.open('/dev/kmsg', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            os.lseek(self.fd, 0, os.SEEK_END)
        except OSError as exc:
            self.failure = str(exc)
            self.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def collect(self, label):
        window = dict(label=label, complete=self.fd is not None, errors=[], messages=0,
                      known_platform_messages=0, gaps=[], log='kernel.jsonl')
        if self.failure:
            window['reason'] = self.failure
        if self.fd is not None:
            with (self.output/'kernel.jsonl').open('a') as log:
                while True:
                    try:
                        data = os.read(self.fd, 1048576)
                    except BlockingIOError:
                        break
                    except OSError as exc:
                        window['complete'] = False
                        window['gaps'].append(str(exc))
                        if exc.errno == errno.EPIPE:
                            self.last_sequence = None
                            continue
                        self.failure = str(exc)
                        self.close()
                        break
                    if not data:
                        break
                    try:
                        record = decode(data)
                    except (ValueError, IndexError) as exc:
                        window['complete'] = False
                        window['gaps'].append('Malformed kernel record: '+str(exc))
                        continue
                    seq = record['sequence']
                    if self.last_sequence is not None and seq != self.last_sequence+1:
                        window['complete'] = False
                        window['gaps'].append(dict(previous=self.last_sequence, next=seq))
                    self.last_sequence = seq
                    record['context'] = label
                    log.write(json.dumps(record)+'\n')
                    window['messages'] += 1
                    if record['category'] == 'known_platform_message':
                        window['known_platform_messages'] += 1
                    elif record['category'] != 'info':
                        window['errors'].append(record)
                        if record['category'] == 'kernel_fault':
                            self.fatal = True
                        if record['category'] == 'log_loss':
                            window['complete'] = False
        qualify(window)
        self.windows.append(window)
        return window

    def summary(self):
        return dict(available=self.failure is None, has_kernel_fault=self.fatal, affects_test_result=False, complete=bool(self.windows) and all(w['complete'] for w in self.windows),
                    clean=bool(self.windows) and all(w['clean'] for w in self.windows),
                    error_messages=sum(len(w['errors']) for w in self.windows),
                    unqualified_messages=sum(w['unqualified_messages'] for w in self.windows),
                    windows=self.windows)

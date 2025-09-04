#!/usr/bin/env python3

# Copyright (c) 2019-2023, NVIDIA CORPORATION. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import argparse
from Jetson import board
import sys
import re
import os


def show_hardware(jetson, header):
    jetson.set_active_header(header)
    hwlist = jetson.hw_addon_get()

    if len(hwlist) == 0:
        print("  No hardware configurations found!")
    else:
        print("  Available hardware modules:")

    for index, hw in enumerate(hwlist):
        print("  %d. %s" % (index + 1, hw))


def configure_dt(jetson, dtbos, eg):
    messages = jetson.configure_dt_for_next_boot(dtbos, eg)
    for message in messages:
        print(message)
    print("Reboot system to reconfigure.")


def configure_jetson(jetson, header, hw):
    jetson.set_active_header(header)
    hwlist = jetson.hw_addon_get()

    if hw not in hwlist:
        raise NameError("No configuration found for %s on %s!" \
                        % (hw, header))

    jetson.hw_addon_load(hw)
    return jetson.hw_addons[hw]


def parse_hw_args(hw_args, num_headers):
    hw_mods = [[None]]
    for n in range(num_headers-1):
      hw_mods.append([])

    for arg in hw_args:
        res = re.match(r'([0-9]+)=(.+)', arg)
        if res:
            idx = int(res.groups()[0]) - 1
            hw_mod = res.groups()[1]
        else:
            idx = 0
            hw_mod = arg

        if (idx < 0) or (idx >= num_headers):
            raise IndexError("Invalid Header number %d!" % (idx + 1))

        hw_mods[idx].append(hw_mod)

    return hw_mods


def main():
    parser = argparse.ArgumentParser("Configure Jetson for a hardware module")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-n", "--name", nargs='*',
                       help="<header-num>=\"<hw-module>\" ...")
    group.add_argument("-l", "--list", help="List of hardware modules",
                       action='store_true')
    args = parser.parse_args()

    jetson = board.Board()
    headers = jetson.get_board_headers()
    dtbos = []
    eg = 0 

    if len(headers) == 0:
        raise RuntimeError("Platform not supported, no headers found!")

    if args.name:
        hw_mods = parse_hw_args(args.name, len(headers))

    for header in headers:
        idx = headers.index(header)

        if args.list:
            if idx == 0:
                print("Header 1 [default]: %s" % header)
            else:
                print("Header %d: %s" % (idx + 1, header))

            show_hardware(jetson, header)
        else:
            hws = hw_mods[idx]
            for i in range(len(hws)):
              hw = hws[i]
              if hw:
                  if ("Exosens Cameras" in hw)::
                      eg = 1
                  else :
                      eg = 0
                  dtbo = configure_jetson(jetson, header, hw)
                  dtbos.append(dtbo)

    if len(dtbos) >= 1:
        configure_dt(jetson, dtbos, eg)


if __name__ == '__main__':
    main()

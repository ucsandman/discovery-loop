#!/bin/bash
cd ~/workspace/discovery-loop
.venv/bin/python ~/workspace/discovery-loop/nightly/lns_laderman.py 18 6 21600 100 > ~/workspace/discovery-loop/nightly/overnight1.log 2>&1

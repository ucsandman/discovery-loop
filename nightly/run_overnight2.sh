#!/bin/bash
cd ~/workspace/discovery-loop
.venv/bin/python ~/workspace/discovery-loop/nightly/lns_laderman.py 19 7 21600 200 > ~/workspace/discovery-loop/nightly/overnight2.log 2>&1

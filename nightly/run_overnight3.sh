#!/bin/bash
cd ~/workspace/discovery-loop
.venv/bin/python ~/workspace/discovery-loop/nightly/lns_laderman.py 0 8 21600 300 > ~/workspace/discovery-loop/nightly/overnight3.log 2>&1

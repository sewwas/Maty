#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/.."
streamlit run Bot1/panel.py --server.port 8501 --server.address 0.0.0.0 --server.headless true

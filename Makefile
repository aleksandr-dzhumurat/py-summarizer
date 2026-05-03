CURRENT_DIR = $(shell pwd)
include .env
export

prepare-dirs:
	mkdir -p ${CURRENT_DIR}/data

run: prepare-dirs
	DATA_DIR=${CURRENT_DIR}/data PYTHONPATH=${CURRENT_DIR} python3 scripts/${SCRIPT}.py $(REPO)

serve: prepare-dirs
	DATA_DIR=${CURRENT_DIR}/data PYTHONPATH=${CURRENT_DIR} uv run uvicorn src.app:app --reload --host 0.0.0.0 --port 8000

test-api:
	DATA_DIR=${CURRENT_DIR}/data PYTHONPATH=${CURRENT_DIR} python3 scripts/test_api.py

gh-login:
	gh auth login

GIST_ID = b4435219cca6b1869e0257ef42420273

publish:
	jq -n \
		--rawfile skill src/py_summarizer/SKILL.md \
		--rawfile skeleton src/py_summarizer/naive_skeleton.py \
		--rawfile utils src/py_summarizer/utils.py \
		'{"files":{"SKILL.md":{"content":$$skill},"naive_skeleton.py":{"content":$$skeleton},"utils.py":{"content":$$utils}}}' \
	| gh api /gists/$(GIST_ID) --method PATCH --input -
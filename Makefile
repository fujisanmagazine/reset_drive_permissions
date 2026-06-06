IMAGE := reset-drive-permissions
TAG := latest
ARGS :=
AUTH_PORT := 8080

.PHONY: help build auth run dry-run clean

help:
	@echo "Usage: make <target> [ARGS='...']"
	@echo ""
	@echo "Targets:"
	@echo "  auth      Authenticate and save token.json (run once)"
	@echo "  build     Build the Docker image"
	@echo "  dry-run   Show files that would be restricted (no changes)"
	@echo "  run       Delete public permissions from Drive files"
	@echo "  clean     Remove the Docker image"
	@echo ""
	@echo "First-time setup:"
	@echo "  make build && make auth"
	@echo "  (On a remote server without a browser, first run:"
	@echo "   ssh -L $(AUTH_PORT):localhost:$(AUTH_PORT) <server>)"
	@echo ""
	@echo "Examples:"
	@echo "  make auth"
	@echo "  make auth AUTH_PORT=9090"
	@echo "  make dry-run"
	@echo "  make dry-run ARGS='-n 10'"
	@echo "  make dry-run ARGS=\"-s 'https://docs.google.com/spreadsheets/d/...'\" "
	@echo "  make run"
	@echo "  make run ARGS='-n 10'"

auth:
	touch token.json
	docker run --rm -it \
		-p $(AUTH_PORT):$(AUTH_PORT) \
		-v $(PWD)/credentials.json:/app/credentials.json \
		-v $(PWD)/token.json:/app/token.json \
		$(IMAGE):$(TAG) --auth --auth-port $(AUTH_PORT) --no-browser

build:
	docker build -t $(IMAGE):$(TAG) .

run:
	@test -f config.json || echo '{}' > config.json
	docker run --rm -it \
		-p $(AUTH_PORT):$(AUTH_PORT) \
		-v $(PWD)/credentials.json:/app/credentials.json \
		-v $(PWD)/token.json:/app/token.json \
		-v $(PWD)/config.json:/app/config.json \
		$(IMAGE):$(TAG) --run --no-browser $(ARGS)

dry-run:
	@test -f config.json || echo '{}' > config.json
	docker run --rm -it \
		-p $(AUTH_PORT):$(AUTH_PORT) \
		-v $(PWD)/credentials.json:/app/credentials.json \
		-v $(PWD)/token.json:/app/token.json \
		-v $(PWD)/config.json:/app/config.json \
		$(IMAGE):$(TAG) --dry-run --no-browser $(ARGS)

clean:
	docker rmi $(IMAGE):$(TAG)

IMAGE := reset-drive-permissions
TAG := latest
ARGS :=

.PHONY: build run dry-run clean

build:
	docker build -t $(IMAGE):$(TAG) .

run:
	docker run --rm -it \
		-v $(PWD)/token.json:/app/token.json \
		$(IMAGE):$(TAG) $(ARGS)

dry-run:
	docker run --rm \
		-v $(PWD)/token.json:/app/token.json \
		$(IMAGE):$(TAG) --dry-run $(ARGS)

clean:
	docker rmi $(IMAGE):$(TAG)

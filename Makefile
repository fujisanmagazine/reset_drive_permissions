IMAGE := reset-drive-permissions
TAG := latest

.PHONY: build run clean

build:
	docker build -t $(IMAGE):$(TAG) .

run:
	docker run --rm \
		-v $(PWD)/token.json:/app/token.json \
		$(IMAGE):$(TAG)

clean:
	docker rmi $(IMAGE):$(TAG)

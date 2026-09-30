FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/api ./cmd/api && CGO_ENABLED=0 go build -trimpath -o /out/worker ./cmd/worker && CGO_ENABLED=0 go build -trimpath -o /out/migrate ./cmd/migrate && CGO_ENABLED=0 go build -trimpath -o /out/runtime-role ./cmd/runtime-role
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/api /api
COPY --from=build /out/worker /worker
COPY --from=build /out/migrate /migrate
COPY --from=build /out/runtime-role /runtime-role
COPY migrations /migrations
USER nonroot:nonroot
ENTRYPOINT ["/api"]

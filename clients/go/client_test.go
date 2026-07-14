package main_test

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	pb "github.com/hewimetall/fastapi-grpc-gateway/clients/go/gen"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func grpcAddr(t *testing.T) string {
	t.Helper()
	addr := os.Getenv("FGG_GRPC_ADDR")
	if addr == "" {
		t.Skip("FGG_GRPC_ADDR not set")
	}
	return addr
}

func dial(t *testing.T) (pb.APIClient, func()) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, err := grpc.DialContext(
		ctx,
		grpcAddr(t),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	return pb.NewAPIClient(conn), func() { _ = conn.Close() }
}

func TestGetHello(t *testing.T) {
	client, closer := dial(t)
	defer closer()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := client.GetHello(ctx, &pb.RpcRequest{})
	if err != nil {
		t.Fatalf("GetHello: %v", err)
	}
	if resp.StatusCode != 200 {
		t.Fatalf("status=%d body=%s", resp.StatusCode, string(resp.Body))
	}
	var payload map[string]any
	if err := json.Unmarshal(resp.Body, &payload); err != nil {
		t.Fatalf("json: %v", err)
	}
	if payload["message"] != "hello" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}

func TestGetUser(t *testing.T) {
	client, closer := dial(t)
	defer closer()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	resp, err := client.GetUser(ctx, &pb.RpcRequest{
		Path: map[string]string{"user_id": "7"},
	})
	if err != nil {
		t.Fatalf("GetUser: %v", err)
	}
	if resp.StatusCode != 200 {
		t.Fatalf("status=%d body=%s", resp.StatusCode, string(resp.Body))
	}
	var payload map[string]any
	if err := json.Unmarshal(resp.Body, &payload); err != nil {
		t.Fatalf("json: %v", err)
	}
	// JSON numbers decode as float64
	if payload["user_id"] != float64(7) {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}

func TestPostCreateItem(t *testing.T) {
	client, closer := dial(t)
	defer closer()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	body, _ := json.Marshal(map[string]any{"name": "widget", "price": 9.5})
	resp, err := client.PostCreateItem(ctx, &pb.RpcRequest{Body: body})
	if err != nil {
		t.Fatalf("PostCreateItem: %v", err)
	}
	if resp.StatusCode != 200 {
		t.Fatalf("status=%d body=%s", resp.StatusCode, string(resp.Body))
	}
	var payload map[string]any
	if err := json.Unmarshal(resp.Body, &payload); err != nil {
		t.Fatalf("json: %v", err)
	}
	if payload["name"] != "widget" {
		t.Fatalf("unexpected payload: %#v", payload)
	}
}

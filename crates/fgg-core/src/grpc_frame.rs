use bytes::{Buf, BufMut, Bytes, BytesMut};
use prost::Message;
use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum GrpcFrameError {
    #[error("grpc frame too short")]
    TooShort,
    #[error("compressed grpc messages not supported")]
    Compressed,
    #[error("grpc frame truncated")]
    Truncated,
    #[error("encode failed: {0}")]
    Encode(String),
}

/// Decode a single uncompressed gRPC data frame → message bytes.
pub fn decode_grpc_payload(buf: &Bytes) -> Result<&[u8], GrpcFrameError> {
    if buf.len() < 5 {
        return Err(GrpcFrameError::TooShort);
    }
    if buf[0] != 0 {
        return Err(GrpcFrameError::Compressed);
    }
    let len = (&buf[1..5]).get_u32() as usize;
    if buf.len() < 5 + len {
        return Err(GrpcFrameError::Truncated);
    }
    Ok(&buf[5..5 + len])
}

/// Encode a prost message into an uncompressed gRPC data frame.
pub fn encode_grpc_payload(msg: &impl Message) -> Result<Bytes, GrpcFrameError> {
    let mut body = BytesMut::new();
    body.put_u8(0);
    let mut proto = BytesMut::new();
    msg.encode(&mut proto)
        .map_err(|e| GrpcFrameError::Encode(e.to_string()))?;
    body.put_u32(proto.len() as u32);
    body.extend_from_slice(&proto);
    Ok(body.freeze())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wire::{JsonResponse, RpcRequest};
    use std::collections::HashMap;

    #[test]
    fn roundtrip_rpc_request() {
        let mut path = HashMap::new();
        path.insert("user_id".into(), "7".into());
        let msg = RpcRequest {
            path,
            query: HashMap::new(),
            body: b"{}".to_vec(),
        };
        let framed = encode_grpc_payload(&msg).unwrap();
        let payload = decode_grpc_payload(&framed).unwrap();
        let decoded = RpcRequest::decode(payload).unwrap();
        assert_eq!(decoded.path.get("user_id").map(String::as_str), Some("7"));
        assert_eq!(decoded.body, b"{}");
    }

    #[test]
    fn roundtrip_json_response() {
        let msg = JsonResponse {
            status_code: 200,
            body: br#"{"ok":true}"#.to_vec(),
            headers: HashMap::from([("content-type".into(), "application/json".into())]),
        };
        let framed = encode_grpc_payload(&msg).unwrap();
        assert_eq!(framed[0], 0);
        let payload = decode_grpc_payload(&framed).unwrap();
        let decoded = JsonResponse::decode(payload).unwrap();
        assert_eq!(decoded.status_code, 200);
        assert_eq!(decoded.body, br#"{"ok":true}"#);
    }

    #[test]
    fn decode_too_short() {
        let buf = Bytes::from_static(&[0, 0, 0]);
        assert_eq!(decode_grpc_payload(&buf), Err(GrpcFrameError::TooShort));
    }

    #[test]
    fn decode_compressed_rejected() {
        let buf = Bytes::from_static(&[1, 0, 0, 0, 0]);
        assert_eq!(decode_grpc_payload(&buf), Err(GrpcFrameError::Compressed));
    }

    #[test]
    fn decode_truncated() {
        let buf = Bytes::from_static(&[0, 0, 0, 0, 10, 1, 2]);
        assert_eq!(decode_grpc_payload(&buf), Err(GrpcFrameError::Truncated));
    }

    #[test]
    fn decode_empty_message() {
        let buf = Bytes::from_static(&[0, 0, 0, 0, 0]);
        let payload = decode_grpc_payload(&buf).unwrap();
        assert!(payload.is_empty());
    }
}

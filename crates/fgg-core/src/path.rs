/// Percent-encode a path segment (RFC 3986 unreserved left as-is).
pub fn urlencoding_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.as_bytes() {
        match *b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

/// Replace `{name}` placeholders in a path template.
pub fn fill_path(template: &str, params: &std::collections::HashMap<String, String>) -> String {
    let mut path = template.to_string();
    for (k, v) in params {
        path = path.replace(&format!("{{{k}}}"), &urlencoding_encode(v));
    }
    path
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn fill_simple() {
        let mut p = HashMap::new();
        p.insert("user_id".into(), "42".into());
        assert_eq!(fill_path("/api/users/{user_id}", &p), "/api/users/42");
    }

    #[test]
    fn fill_encodes_special() {
        let mut p = HashMap::new();
        p.insert("q".into(), "a b/c".into());
        assert_eq!(fill_path("/s/{q}", &p), "/s/a%20b%2Fc");
    }

    #[test]
    fn encode_unreserved_passthrough() {
        assert_eq!(urlencoding_encode("Abc-_.~09"), "Abc-_.~09");
    }

    #[test]
    fn fill_missing_param_leaves_placeholder() {
        let p = HashMap::new();
        assert_eq!(fill_path("/x/{id}", &p), "/x/{id}");
    }
}

-- Earlier rows hashed the submitted JSON bytes, while jsonb changed their
-- representation. Align every stored checksum with the snapshot served by GET.
UPDATE scenarios
SET spec_sha256 = encode(sha256(convert_to(spec::text, 'UTF8')), 'hex')
WHERE spec_sha256 <> encode(sha256(convert_to(spec::text, 'UTF8')), 'hex');

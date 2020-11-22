mkdir -p mytests/data

dd if=/dev/urandom of=mytests/data/small.txt bs=KB count=1
dd if=/dev/urandom of=mytests/data/medium.txt bs=MB count=1
dd if=/dev/urandom of=mytests/data/large.txt bs=MB count=100

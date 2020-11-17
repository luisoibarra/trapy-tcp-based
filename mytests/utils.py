import hashlib

def file_hash(f):
    with open(f, 'rb') as fp:
        data = fp.read()
        return hashlib.sha1(data).hexdigest()


def file_hashes(*files):
    hashes = dict()

    for f in files:
        sha1sum = file_hash(f)
        hashes[f] = sha1sum

    return hashes
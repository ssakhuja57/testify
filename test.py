def xpath_get(mydict, path):
    elem = mydict
    try:
        for x in path.strip("/").split("/"):
            try:
                x = int(x)
                elem = elem[x]
            except ValueError:
                elem = elem.get(x)
    except:
        pass

    return elem

d = {
    'a': 'b',
    'c': {
        'foo': 'bar',
        'foo2': 'bar2'
        },
    'l': [
        [1,2,3],
        [4,5,6]
        ],
    }

print xpath_get(d, '/l/1/1')
print xpath_get(d, '/c/foo')
print xpath_get(d, '/c/foo3')


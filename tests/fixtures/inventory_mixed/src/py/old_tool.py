import sys

def main():
    print "hello from python 2"
    try:
        pass
    except ValueError, e:
        sys.exit(1)

default:
	python3 -m venv --prompt 'api' .
	./bin/pip install --upgrade -r requirements.txt

clean:
	rm -rf bin lib pyvenv.cfg

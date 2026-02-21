.PHONY: clean clean-all clean-dry

clean:
	./clean_workspace.sh --runtime

clean-all:
	./clean_workspace.sh --all

clean-dry:
	./clean_workspace.sh --runtime --dry-run

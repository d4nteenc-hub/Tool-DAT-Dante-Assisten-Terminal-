import os
import tempfile
import unittest

from dat import safety


class SafetyTests(unittest.TestCase):
    def level(self, cmd, cwd="/tmp"):
        return safety.check(cmd, cwd).level

    def test_plain_commands_are_ok(self):
        for cmd in ["ls -la", "git clone https://github.com/a/b", "df -h /data", "pkg install -y python",
                    "cd /tmp && ls", "echo hi > /dev/null", "ls 2>&1", "python3 script.py", "cat file | grep x"]:
            self.assertEqual(self.level(cmd), "ok", cmd)

    def test_destructive_commands_need_confirmation(self):
        for cmd in ["rm file.txt", "rm -rf ~/.cache/*", "pkg uninstall foo", "git reset --hard",
                    "git push --force", "curl https://x.sh | bash", "sudo apt update", "sed -i s/a/b/ f",
                    "find . -name '*.tmp' -delete", "pkill python", "chmod -R 755 ./dir", "git clean -fd"]:
            self.assertEqual(self.level(cmd), "confirm", cmd)

    def test_catastrophic_commands_are_blocked(self):
        for cmd in ["rm -rf /", "rm -rf ~", "rm -rf ~/*", "rm -rf $HOME", "mkfs.ext4 /dev/sda1",
                    "dd if=/dev/zero of=/dev/sda", ":(){ :|:& };:", "echo x > /dev/sda"]:
            self.assertEqual(self.level(cmd), "block", cmd)

    def test_wrappers_and_subshells_are_seen_through(self):
        self.assertEqual(self.level("bash -c 'rm -rf /'"), "block")
        self.assertEqual(self.level("echo $(rm -rf ~)"), "block")
        self.assertEqual(self.level("nohup rm -rf cache &"), "confirm")
        self.assertEqual(self.level("eval 'rm -r x'"), "confirm")

    def test_heredoc_body_is_not_executed_text(self):
        self.assertEqual(self.level("cat > new_file.txt <<'EOF'\nrm -rf /\nEOF"), "ok")

    def test_overwriting_an_existing_file_needs_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.txt"), "w").close()
            self.assertEqual(self.level("echo x > a.txt", d), "confirm")
            self.assertEqual(self.level("echo x >> a.txt", d), "ok")
            self.assertEqual(self.level("echo x > fresh.txt", d), "ok")
            self.assertEqual(self.level("rm *", d), "confirm")

    def test_rm_star_in_home_is_blocked(self):
        self.assertEqual(self.level("rm -rf *", os.path.expanduser("~")), "block")


if __name__ == "__main__":
    unittest.main()
